"""YAML 워크플로 로드·검증. 규칙은 docs/contract.md 3절.

`load()`는 문제를 전부 모아 한 번에 `WorkflowError`로 알린다. 통과하면 단계 공통 키
(`name`, `timeout`, `required`)의 기본값을 채운 워크플로를 돌려준다.
"""

import importlib
import os
import pkgutil
import re
from pathlib import Path

import yaml

from wetrun.notify import WHEN_CHOICES

TOP_KEYS = {
    "version": True,
    "repository": True,
    "snapshot": True,
    "compose": True,
    "refs": False,
    "notify": False,
    "steps": True,
}  # 키 → 필수 여부
SECTION_KEYS = {
    "repository": ({"path"}, {"password"}),
    "snapshot": ({"tag"}, {"select"}),
    "compose": ({"files"}, {"env_file", "env", "mem_limit"}),
    "notify": ({"discord"}, {"when"}),
}  # 섹션 → (필수, 선택)
COMMON_KEYS = {"use", "name", "timeout", "required"}
DEFAULT_TIMEOUT = 300
# 실행기가 직접 하는 단계 → (필수 키, 선택 키). 내장 검사는 steps/*.py 상수가 기준
RUNNER_STEPS = {
    "restore": (set(), set()),
    "up": (set(), {"services"}),
    "exec": ({"service", "command"}, {"stdin"}),
}
SCRIPT_STEP = {"script": ({"image", "command"}, set())}
# 복원 후에야 생기는 경로. check-input에서는 존재를 확인하지 않는다
RUN_PLACEHOLDERS = ("{restore}", "{run}")
RESTIC_URL = re.compile(r"^[a-z0-9]+:")  # s3:, sftp:, rest: 등


class WorkflowError(Exception):
    def __init__(self, problems: list[str]):
        super().__init__("\n".join(problems))
        self.problems = problems


def builtin_checks() -> dict[str, tuple[set[str], set[str]]]:
    """`wetrun/steps/`의 내장 검사. `_`로 시작하거나 `REQUIRED_KEYS`가 없는 모듈은 검사가 아니다."""
    from wetrun import steps

    found = {}
    for mod in pkgutil.iter_modules(steps.__path__):
        if mod.name.startswith("_"):
            continue
        m = importlib.import_module(f"wetrun.steps.{mod.name}")
        if hasattr(m, "REQUIRED_KEYS"):
            found[mod.name] = (set(m.REQUIRED_KEYS), set(getattr(m, "OPTIONAL_KEYS", ())))
    return found


def load(path: Path) -> dict:
    try:
        wf = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as e:
        raise WorkflowError([f"워크플로를 읽지 못함: {e}"]) from e
    if not isinstance(wf, dict):
        raise WorkflowError(["워크플로 최상위는 매핑이어야 함"])

    base = path.parent
    problems = _check_keys("", wf, {k for k, req in TOP_KEYS.items() if req}, set(TOP_KEYS))
    if wf.get("version") not in (None, 1):
        problems.append(f"version: 지원하지 않는 버전 {wf['version']!r} (1만 지원)")
    for section, (req, opt) in SECTION_KEYS.items():
        if isinstance(wf.get(section), dict):
            problems += _check_keys(f"{section}.", wf[section], req, req | opt)
        elif section in wf:
            problems.append(f"{section}: 매핑이어야 함")

    repo = (wf.get("repository") or {}).get("path")
    if isinstance(repo, str) and not RESTIC_URL.match(repo):
        problems += _check_file("repository.path", base, repo)
    compose = wf.get("compose") if isinstance(wf.get("compose"), dict) else {}
    files = compose.get("files")
    if "files" in compose and not (isinstance(files, list) and files):
        problems.append("compose.files: 비어 있지 않은 목록이어야 함")
    for f in files if isinstance(files, list) else []:
        problems += _check_file("compose.files", base, f)
    mem = compose.get("mem_limit")
    if "mem_limit" in compose and not (
        isinstance(mem, str)
        or (isinstance(mem, dict) and all(isinstance(v, str) for v in mem.values()))
    ):
        problems.append('compose.mem_limit: "2g" 같은 문자열이나 서비스별 매핑이어야 함')
    if "env_file" in compose:
        problems += _check_file("compose.env_file", base, compose["env_file"])
    if "refs" in wf:
        problems += _check_file("refs", base, wf["refs"])

    if isinstance(wf.get("notify"), dict):
        problems += _check_notify(wf["notify"])

    steps = wf.get("steps")
    if "steps" in wf and not (isinstance(steps, list) and steps):
        problems.append("steps: 비어 있지 않은 목록이어야 함")
        steps = []
    problems += _check_steps(steps or [], base)
    problems += [f"env:{v}: 환경 변수가 비어 있음" for v in sorted(_empty_env_refs(wf))]

    if problems:
        raise WorkflowError(problems)
    return wf


def _check_steps(steps: list, base: Path) -> list[str]:
    known = {**RUNNER_STEPS, **SCRIPT_STEP, **builtin_checks()}
    problems, names = [], set()
    for i, step in enumerate(steps):
        where = f"steps[{i}]"
        if not isinstance(step, dict) or "use" not in step:
            problems.append(f"{where}: `use`가 있는 매핑이어야 함")
            continue
        use = step["use"]
        if use not in known:
            problems.append(f"{where}: 모르는 use {use!r} (가능: {', '.join(sorted(known))})")
            continue
        req, opt = known[use]
        problems += _check_keys(f"{where}.", step, req, req | opt | COMMON_KEYS)

        step.setdefault("name", use)
        step.setdefault("timeout", DEFAULT_TIMEOUT)
        step.setdefault("required", True)
        if not isinstance(step["name"], str) or not step["name"]:
            problems.append(f"{where}.name: 비어 있지 않은 문자열이어야 함")
            continue
        where = f"{where}({step['name']})"
        if step["name"] in names:
            problems.append(f"{where}: name이 겹침")
        names.add(step["name"])
        t = step["timeout"]
        if isinstance(t, bool) or not isinstance(t, int) or t <= 0:
            problems.append(f"{where}.timeout: 양의 정수(초)여야 함")
        if not isinstance(step["required"], bool):
            problems.append(f"{where}.required: true 또는 false여야 함")
        elif use in RUNNER_STEPS and not step["required"]:
            problems.append(f"{where}.required: 실행기 단계는 false로 둘 수 없음")
        if use == "exec" and "stdin" in step:
            problems += _check_file(f"{where}.stdin", base, step["stdin"])
    return problems


def _check_notify(n: dict) -> list[str]:
    problems = []
    if True in n:  # YAML은 `on:`을 true로 읽는다
        problems.append("notify: `on` 대신 `when`을 쓴다 (YAML은 on을 true로 읽음)")
    d = n.get("discord")
    if "discord" in n and not (isinstance(d, str) and d.startswith("env:")):
        # 웹훅 주소를 그대로 적으면 커밋되어 공개된다
        problems.append("notify.discord: 웹훅 주소는 비밀 값이라 env:<변수>로만 쓸 수 있음")
    if "when" in n:
        when = [n["when"]] if isinstance(n["when"], str) else n["when"]
        if not (isinstance(when, list) and when and all(w in WHEN_CHOICES for w in when)):
            problems.append(f"notify.when: {', '.join(WHEN_CHOICES)} 중에서 골라야 함")
    return problems


def _check_keys(where: str, d: dict, required: set[str], allowed: set[str]) -> list[str]:
    # key=str: YAML은 `on:` 같은 키를 true로 읽어 글자 키와 섞일 수 있다
    missing = [f"{where}{k}: 필수 키가 없음" for k in sorted(required - d.keys(), key=str)]
    unknown = [f"{where}{k}: 모르는 키" for k in sorted(d.keys() - allowed, key=str)]
    return missing + unknown


def _check_file(where: str, base: Path, value) -> list[str]:
    if not isinstance(value, str):
        return [f"{where}: 경로 문자열이어야 함"]
    if value.startswith(RUN_PLACEHOLDERS):
        return []
    if not (base / value).exists():
        return [f"{where}: 파일이 없음 ({value})"]
    return []


def _empty_env_refs(obj) -> set[str]:
    """`env:<변수>` 참조 중 값이 비어 있는 변수."""
    if isinstance(obj, dict):
        return set().union(*map(_empty_env_refs, obj.values()))
    if isinstance(obj, list):
        return set().union(*map(_empty_env_refs, obj))
    if isinstance(obj, str) and obj.startswith("env:") and not os.environ.get(obj[4:]):
        return {obj[4:]}
    return set()
