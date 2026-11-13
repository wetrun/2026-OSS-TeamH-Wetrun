"""단계 실행·판정·항상 정리. 규칙은 docs/contract.md 4절, 실행기 단계 판정은 #13.

실행마다 전용 Compose 프로젝트와 실행 디렉터리를 만들고, YAML 순서대로 단계를 실행한다.
필수 단계가 pass가 아니면 남은 단계는 skipped. 성공·실패·중단 모두에서 정리한다.

ponytail: 중복 실행 방지(락)는 없다. 실행마다 프로젝트 이름이 달라 겹쳐도 안전하다.
예약 실행을 붙일 때 추가한다.
"""

import hashlib
import json
import os
import signal
import subprocess
import time
from datetime import datetime
from pathlib import Path

import wetrun
from wetrun import isolation as iso
from wetrun import workflow
from wetrun.contract import CHECK_EXIT_STATUS, CHECK_TIMEOUT_GRACE_S, RunResult, Status, StepResult
from wetrun.restic import Restic, ResticError

CHECK_IMAGE = "python:3.12-slim"
# 실행 디렉터리를 만들 곳. 복원한 데이터가 들어가므로 공간이 넉넉한 곳으로 바꿀 수 있다
WORK_BASE = Path(os.environ.get("WETRUN_WORKDIR", "/var/tmp/wetrun"))
STDERR_LINES = 20
NOBODY = 65534
MASK = "***"


class _Run:
    """실행 하나의 상태. 단계 함수들이 공유한다."""

    def __init__(self, wf: dict, path: Path):
        self.wf, self.base = wf, path.parent
        self.run_id = iso.new_run_id()
        self.project = iso.project_name(self.run_id)
        self.run_dir = iso.make_run_dir(WORK_BASE, self.project)
        self.restore_dir = self.run_dir / "restore"
        self.compose_file: Path | None = None
        self.snapshot_id = ""
        self.images: dict[str, str] = {}

    # ---- 값 풀기 ----

    def resolve(self, value):
        """`env:<변수>`를 실제 값으로, `{restore}`·`{run}`을 실행 디렉터리 경로로 바꾼다."""
        if isinstance(value, dict):
            return {k: self.resolve(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.resolve(v) for v in value]
        if isinstance(value, str):
            if value.startswith("env:"):
                return os.environ[value[4:]]
            return value.replace("{restore}", str(self.restore_dir)).replace(
                "{run}", str(self.run_dir)
            )
        return value

    def path(self, value: str) -> Path:
        """워크플로 경로. 자리표시자가 있으면 실행 디렉터리, 아니면 워크플로 파일 기준."""
        return (
            Path(self.resolve(value))
            if value.startswith(workflow.RUN_PLACEHOLDERS)
            else (self.base / value)
        )

    def compose(self, *args: str, timeout: float | None = None, stdin=None):
        assert self.compose_file
        cmd = ["docker", "compose", "-p", self.project, "-f", str(self.compose_file), *args]
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, stdin=stdin, check=False
        )

    # ---- 단계 ----

    def restore(self, step: dict) -> tuple[Status, str, dict]:
        repo, snap = self.wf["repository"], self.wf["snapshot"]
        location = repo["path"]
        if not workflow.RESTIC_URL.match(location):
            location = str(self.base / location)
        password = self.resolve(repo["password"]) if "password" in repo else None
        restic = Restic(location, password)
        try:
            found = restic.preflight(snap["tag"], snap.get("select", "latest"), self.run_dir)
            self.snapshot_id = found["id"]
            restic.restore(found["id"], self.restore_dir, timeout=step["timeout"])
        except ResticError as e:
            return e.status, e.message, e.evidence
        return (
            Status.PASS,
            "스냅샷 복원",
            {"snapshot_id": found["id"], "bytes": found["restore_size"]},
        )

    def up(self, step: dict) -> tuple[Status, str, dict]:
        if self.compose_file is None:
            c = self.wf["compose"]
            try:
                self.compose_file = iso.prepare(
                    [self.base / f for f in c["files"]],
                    self.run_dir,
                    self.project,
                    self.base / c["env_file"] if "env_file" in c else None,
                    {k: str(v) for k, v in self.resolve(c.get("env", {})).items()},
                )
            except iso.IsolationError as e:
                return Status.ERROR, "compose 설정을 쓸 수 없음", {"reason": str(e)}
        services = step.get("services", [])
        args = ["up", "-d", "--wait", "--wait-timeout", str(step["timeout"]), *services]
        try:
            r = self.compose(*args, timeout=step["timeout"] + CHECK_TIMEOUT_GRACE_S)
        except subprocess.TimeoutExpired:
            return Status.ERROR, "docker compose가 응답하지 않음", {}
        states = self._states()
        self._record_images()
        if r.returncode == 0:
            return Status.PASS, "서비스 기동", {"containers": states}
        evidence = {"exit_code": r.returncode, "stderr": _tail(r.stderr), "containers": states}
        if not states:  # 컨테이너를 만들지도 못함: 이미지 없음 등 환경 문제
            return Status.ERROR, "컨테이너를 만들지 못함", evidence
        return Status.FAIL, "서비스가 정상 상태가 되지 못함", evidence

    def exec(self, step: dict) -> tuple[Status, str, dict]:
        service = step["service"]
        running = {s["service"] for s in self._states() if s["state"] == "running"}
        if self.compose_file is None or service not in running:
            return Status.ERROR, f"서비스 {service} 컨테이너가 실행 중이 아님", {}
        stdin = None
        if "stdin" in step:
            src = self.path(step["stdin"])
            if not src.is_file():  # 복원한 백업에 들어 있어야 할 파일이 없음
                return Status.FAIL, "입력 파일이 없음", {"stdin": step["stdin"]}
            stdin = src.open("rb")
        try:
            r = subprocess.run(
                ["docker", "compose", "-p", self.project, "-f", str(self.compose_file),
                 "exec", "-T", service, *self.resolve(step["command"])],
                stdin=stdin, capture_output=True, timeout=step["timeout"], check=False,
            )  # fmt: skip
        except subprocess.TimeoutExpired:
            return Status.ERROR, f"시간 초과 ({step['timeout']}초)", {}
        finally:
            if stdin:
                stdin.close()
        evidence = {"exit_code": r.returncode, "stderr": _tail(r.stderr.decode(errors="replace"))}
        if r.returncode == 0:
            return Status.PASS, "명령 성공", {"exit_code": 0}
        if r.returncode in (126, 127, 137):
            return Status.ERROR, "명령을 실행하지 못했거나 강제 종료됨", evidence
        return Status.FAIL, "명령이 실패함", evidence

    def check(self, step: dict, index: int) -> tuple[Status, str, dict]:
        """검사 컨테이너를 서비스 네트워크에 띄우고 result.json과 종료 코드로 판정한다."""
        if self.compose_file is None:
            return Status.ERROR, "기동한 서비스가 없음 (up 단계가 먼저 필요)", {}
        io = self.run_dir / f"check-{index}"
        (io / "out").mkdir(parents=True, mode=0o700)
        _write_private(io / "step.json", self.resolve(step))
        refs = self.base / self.wf["refs"] if "refs" in self.wf else None
        _write_private(io / "refs.json", json.loads(refs.read_text()) if refs else {})
        if os.getuid() == 0:  # 검사는 nobody로 돈다 (isolation.check_user)
            for p in (io, io / "out", io / "step.json", io / "refs.json"):
                os.chown(p, NOBODY, NOBODY)

        name = f"{self.project}-check-{index}"
        mounts = [
            "-v", f"{io / 'step.json'}:/wetrun/step.json:ro",
            "-v", f"{io / 'refs.json'}:/wetrun/refs.json:ro",
            "-v", f"{io / 'out'}:/wetrun/out",
        ]  # fmt: skip
        if step["use"] == "script":
            image, command = step["image"], self.resolve(step["command"])
        else:
            src = Path(wetrun.__file__).parent
            mounts += ["-v", f"{src}:/opt/wetrun/wetrun:ro"]
            mounts += ["-e", "PYTHONPATH=/opt/wetrun", "-e", "PYTHONDONTWRITEBYTECODE=1"]
            image, command = CHECK_IMAGE, ["python", "-m", f"wetrun.steps.{step['use']}"]
        hardening = iso.hardening_args(self.project, self._network())
        cmd = ["docker", "run", "--rm", "--name", name, *hardening, *mounts, image, *command]
        try:
            r = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=step["timeout"] + CHECK_TIMEOUT_GRACE_S,
                check=False,
            )
        except subprocess.TimeoutExpired:
            subprocess.run(["docker", "kill", name], capture_output=True, check=False)
            return (
                Status.ERROR,
                f"검사가 시간 안에 끝나지 않음 ({step['timeout']}+{CHECK_TIMEOUT_GRACE_S}초)",
                {},
            )
        return _check_result(r.returncode, io / "out" / "result.json", r.stderr)

    # ---- 도움 ----

    def _states(self) -> list[dict]:
        if self.compose_file is None:
            return []
        r = self.compose("ps", "-a", "--format", "json")
        rows = []
        for line in r.stdout.splitlines():
            line = line.strip()
            if line:
                data = json.loads(line)
                rows += data if isinstance(data, list) else [data]
        return [
            {"service": c.get("Service"), "state": c.get("State"), "health": c.get("Health", ""),
             "exit_code": c.get("ExitCode")}
            for c in rows
        ]  # fmt: skip

    def _record_images(self) -> None:
        r = self.compose("images", "--format", "json")
        try:
            for img in json.loads(r.stdout or "[]"):
                self.images[img.get("ContainerName", "")] = (
                    f"{img.get('Repository')}:{img.get('Tag')}@{img.get('ID')}"
                )
        except json.JSONDecodeError:
            pass  # 기록용. 실패해도 판정에는 영향 없음

    def _network(self) -> str:
        names = json.loads(self.compose_file.read_text()).get("networks") or {"default": {}}
        return f"{self.project}_{'default' if 'default' in names else next(iter(names))}"


def run(path: Path) -> RunResult:
    """워크플로를 실행한다. 입력 오류는 workflow.WorkflowError로 아무것도 띄우기 전에 알린다."""
    wf = workflow.load(path)
    started, t0 = datetime.now().astimezone().isoformat(timespec="seconds"), time.monotonic()
    ctx = _Run(wf, path)
    results: list[StepResult] = []
    previous = signal.signal(signal.SIGTERM, _raise_interrupt)
    try:
        iso.ensure_unused(ctx.project)
        iso.ensure_visible(ctx.run_dir)
        stopped = False
        for i, step in enumerate(wf["steps"]):
            if stopped:
                results.append(_result(step, Status.SKIPPED, "앞 필수 단계가 통과하지 못함", {}, 0))
                continue
            s0 = time.monotonic()
            try:
                status, message, evidence = _dispatch(ctx, step, i)
            except KeyboardInterrupt:
                results.append(_result(step, Status.ERROR, "중단됨", {}, time.monotonic() - s0))
                stopped = True
                continue
            results.append(_result(step, status, message, evidence, time.monotonic() - s0))
            stopped = step["required"] and status != Status.PASS
    finally:
        signal.signal(signal.SIGTERM, previous)
        cleanup_errors = iso.cleanup(ctx.project, ctx.run_dir)

    secrets = _secrets(wf)
    return RunResult(
        run_id=ctx.run_id,
        snapshot_id=ctx.snapshot_id,
        workflow_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        started_at=started,
        duration_s=round(time.monotonic() - t0, 1),
        steps=[_mask(r, secrets) for r in results],
        images=ctx.images,
        cleanup_errors=cleanup_errors,
    )


def _dispatch(ctx: _Run, step: dict, index: int) -> tuple[Status, str, dict]:
    if step["use"] in workflow.RUNNER_STEPS:
        return getattr(ctx, step["use"])(step)
    return ctx.check(step, index)


def _check_result(code: int, result_file: Path, stderr: str) -> tuple[Status, str, dict]:
    """계약 2절: 종료 코드와 result.json의 status가 둘 다 맞을 때만 pass·fail."""
    try:
        result = json.loads(result_file.read_text(encoding="utf-8"))
        status, message = result["status"], str(result.get("message", ""))
        evidence = result.get("evidence") or {}
    except (OSError, ValueError, KeyError, TypeError):
        return (
            Status.ERROR,
            "result.json이 없거나 형식이 틀림",
            {
                "exit_code": code,
                "stderr": _tail(stderr),
            },
        )
    expected = CHECK_EXIT_STATUS.get(code)
    if expected is not None and status == expected:
        return expected, message, evidence
    if expected is None and status == Status.ERROR:
        return Status.ERROR, message, evidence
    return (
        Status.ERROR,
        "종료 코드와 result.json의 status가 맞지 않음",
        {
            "exit_code": code,
            "status": status,
        },
    )


def _result(step, status, message, evidence, duration) -> StepResult:
    return StepResult(
        name=step["name"],
        use=step["use"],
        status=status,
        required=step["required"],
        message=message,
        evidence=evidence,
        duration_s=round(duration, 1),
    )


def _secrets(obj) -> set[str]:
    """`env:`로 참조한 값. 결과에 섞여 있으면 가린다."""
    if isinstance(obj, dict):
        return set().union(*map(_secrets, obj.values()))
    if isinstance(obj, list):
        return set().union(*map(_secrets, obj))
    if isinstance(obj, str) and obj.startswith("env:") and os.environ.get(obj[4:]):
        return {os.environ[obj[4:]]}
    return set()


def _mask(result: StepResult, secrets: set[str]) -> StepResult:
    text = json.dumps([result.message, result.evidence], ensure_ascii=False)
    for s in sorted(secrets, key=len, reverse=True):
        text = text.replace(json.dumps(s)[1:-1], MASK)
    result.message, result.evidence = json.loads(text)
    return result


def _write_private(path: Path, data) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def _tail(text: str) -> list[str]:
    return text.strip().splitlines()[-STDERR_LINES:]


def _raise_interrupt(signum, frame):
    raise KeyboardInterrupt
