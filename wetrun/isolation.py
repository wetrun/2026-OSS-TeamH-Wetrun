"""격리 규칙과 정리.

검증용 서비스는 실행마다 전용 Compose 프로젝트(`wetrun-<run_id>`)로 띄운다.

- 원본 compose를 `docker compose config`로 정규화한 뒤, 운영 자원에 닿을 수 있는 설정
  (external 볼륨·네트워크, 실행 디렉터리 밖 bind, docker.sock, host 네임스페이스, privileged)이
  있으면 실행을 거부한다.
- 운영과 겹칠 수 있는 설정(container_name, ports)은 지우고, 모든 네트워크를 internal로 바꿔
  외부 통신을 막는다.
- 정리는 프로젝트 라벨로 찾은 자원과 실행 디렉터리만 지운다. `wetrun-` 이름 규칙 밖의
  프로젝트는 절대 건드리지 않는다. 정리는 예외를 던지지 않고 오류 목록을 돌려준다.
"""

import json
import os
import re
import secrets
import shutil
import stat
import subprocess
from datetime import datetime
from pathlib import Path

PREFIX = "wetrun-"
COMPOSE_LABEL = "com.docker.compose.project"
# wetrun이 compose 밖에서 직접 만드는 컨테이너(검사 등)에 붙이는 라벨
RUN_LABEL = "wetrun.project"
# ponytail: 다른 uid(예: DB 컨테이너)가 만든 파일을 지울 때 쓰는 이미지. 오프라인이면 미리 pull 필요
CLEANUP_IMAGE = "alpine:3"

# 읽기 전용이면 허용하는 호스트 파일. 시간대를 맞추려고 공식 compose에 흔히 있다
READ_ONLY_HOST_FILES = {"/etc/localtime", "/etc/timezone"}

# 서비스별 메모리 상한 기본값. 검증 서비스가 메모리를 다 쓰면 커널이 운영 서비스를 죽일 수 있어,
# 넘치면 검증 컨테이너만 죽게 한다. 워크플로의 compose.mem_limit으로 바꾼다.
# ponytail: 서비스마다 묶을 뿐 합계는 묶지 않는다. 합계가 넘치면 여전히 전역 OOM이 날 수 있다.
# 실행 이력의 최대 사용량으로 시작 전 여유를 확인하는 방식으로 보완한다.
DEFAULT_MEM_LIMIT = "2g"

_PROJECT_RE = re.compile(r"^wetrun-[a-z0-9][a-z0-9-]*$")


class IsolationError(Exception):
    pass


def new_run_id() -> str:
    return f"{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(3)}"


def project_name(run_id: str) -> str:
    name = PREFIX + run_id.lower()
    if not _PROJECT_RE.match(name):
        raise IsolationError(f"사용할 수 없는 run_id: {run_id!r}")
    return name


def make_run_dir(base: Path, project: str) -> Path:
    """실행 디렉터리 `<base>/<project>`를 만든다. 이미 있으면 다른 실행과 겹친 것이므로 실패."""
    run_dir = base / project
    base.mkdir(parents=True, exist_ok=True)
    ensure_private_dir(base)
    run_dir.mkdir(mode=0o700)
    return run_dir


def ensure_private_dir(path: Path) -> None:
    """본인 소유이고, 링크가 아니고, 남이 쓸 수 없는 폴더인지 확인한다.

    /tmp·/var/tmp처럼 여러 사람이 쓰는 곳에 다른 사용자가 같은 이름의 폴더나 링크를 먼저
    만들어 두면, 비밀 값이 든 파일이 그 사람 손에 들어가거나 엉뚱한 파일이 덮어써진다.
    """
    st = os.lstat(path)
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise IsolationError(f"폴더가 아니거나 링크임: {path}")
    if st.st_uid != os.getuid():
        raise IsolationError(f"다른 사용자 소유 폴더라 쓰지 않음: {path} (uid {st.st_uid})")
    if st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise IsolationError(f"남이 쓸 수 있는 폴더라 쓰지 않음: {path}. chmod go-w로 바꾼다")


def violations(config: dict, run_dir: Path) -> list[str]:
    """정규화된 compose 설정에서 격리 규칙 위반을 찾는다."""
    root = run_dir.resolve()
    found = []
    for kind in ("networks", "volumes"):
        for name, spec in (config.get(kind) or {}).items():
            if (spec or {}).get("external"):
                found.append(f"{kind}.{name}: external은 운영 자원일 수 있어 허용하지 않음")
    # 이름 있는 볼륨도 driver_opts(type: none, o: bind, device: <호스트 경로>)나
    # 다른 드라이버(NFS 등)로 운영 경로·공유 저장소에 붙을 수 있다.
    # 검증 볼륨은 기본 local 드라이버의 빈 볼륨만 쓴다
    for name, spec in (config.get("volumes") or {}).items():
        spec = spec or {}
        if spec.get("driver_opts") or spec.get("driver", "local") != "local":
            found.append(
                f"volumes.{name}: driver·driver_opts는 운영 경로에 붙을 수 있어 허용하지 않음"
            )
    # secrets·configs의 file은 bind 마운트와 같다
    for kind in ("secrets", "configs"):
        for name, spec in (config.get(kind) or {}).items():
            source = (spec or {}).get("file")
            if source and not Path(source).resolve().is_relative_to(root):
                found.append(f"{kind}.{name}: 실행 디렉터리 밖 파일 ({source})")
    for svc, spec in (config.get("services") or {}).items():
        if spec.get("privileged"):
            found.append(f"services.{svc}: privileged 허용하지 않음")
        if spec.get("devices"):
            found.append(f"services.{svc}: devices 허용하지 않음")
        # privileged와 같은 효과를 내거나 컨테이너 격리를 약하게 하는 설정
        if spec.get("cap_add"):
            found.append(f"services.{svc}: cap_add 허용하지 않음 ({', '.join(spec['cap_add'])})")
        weak = [o for o in spec.get("security_opt") or [] if _weakens_security(o)]
        if weak:
            found.append(f"services.{svc}: 보안 장치를 끄는 security_opt ({', '.join(weak)})")
        if spec.get("cgroup_parent"):
            found.append(f"services.{svc}: cgroup_parent 허용하지 않음")
        for src in spec.get("volumes_from") or []:
            if str(src).startswith("container:"):
                found.append(f"services.{svc}: 바깥 컨테이너의 volumes_from ({src})")
        for key in ("network_mode", "pid", "ipc", "uts", "userns_mode"):
            value = spec.get(key) or ""
            if value == "host" or value.startswith(("container:", "service:")):
                found.append(f"services.{svc}.{key}: {value} 허용하지 않음")
        for mount in spec.get("volumes") or []:
            if mount.get("type") != "bind":
                continue
            source = mount.get("source", "")
            if source in READ_ONLY_HOST_FILES and mount.get("read_only"):
                continue
            if source.endswith("docker.sock"):
                found.append(f"services.{svc}: Docker 소켓 마운트 허용하지 않음 ({source})")
            elif not Path(source).resolve().is_relative_to(root):
                found.append(f"services.{svc}: 실행 디렉터리 밖 bind 마운트 ({source})")
    return found


def _weakens_security(option: str) -> bool:
    o = option.replace("=", ":").lower()
    return "unconfined" in o or o in ("label:disable", "no-new-privileges:false")


def sanitize(config: dict, project: str, mem_limit: str | dict | None = None) -> dict:
    """운영과 겹칠 수 있는 설정을 지우고 네트워크를 internal로 바꾼 사본을 돌려준다.

    메모리 상한: `mem_limit`이 문자열이면 모든 서비스, 매핑이면 서비스별로 쓴다. 지정하지 않은
    서비스는 compose에 이미 있는 상한을 두고, 없으면 DEFAULT_MEM_LIMIT를 붙인다.
    """
    # 오래된 Compose(2.16 등)는 config 출력에 `"command": null`처럼 빈 값을 넣고, 다시 읽을 때는
    # 거부한다. 빈 값은 "지정하지 않음"과 같으므로 지운다
    c = _drop_nulls(json.loads(json.dumps(config)))
    c["name"] = project
    per_service = mem_limit if isinstance(mem_limit, dict) else {}
    default = mem_limit if isinstance(mem_limit, str) else None
    for name, spec in (c.get("services") or {}).items():
        limits = ((spec.get("deploy") or {}).get("resources") or {}).get("limits") or {}
        if name in per_service or default:
            spec["mem_limit"] = per_service.get(name, default)
        elif not spec.get("mem_limit") and not limits.get("memory"):
            spec["mem_limit"] = DEFAULT_MEM_LIMIT
        spec.pop("container_name", None)
        spec.pop("ports", None)
        spec["restart"] = "no"
        spec["labels"] = {**(spec.get("labels") or {}), RUN_LABEL: project}
    networks = c.get("networks") or {"default": {}}
    c["networks"] = {name: {**(spec or {}), "internal": True} for name, spec in networks.items()}
    return c


def _drop_nulls(value):
    if isinstance(value, dict):
        return {k: _drop_nulls(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_drop_nulls(v) for v in value]
    return value


def prepare(
    compose_files: list[Path],
    run_dir: Path,
    project: str,
    env_file: Path | None = None,
    env: dict[str, str] | None = None,
    mem_limit: str | dict | None = None,
) -> Path:
    """원본 compose를 검사·변환해 `<run_dir>/compose.wetrun.json`으로 쓴다.

    상대 경로는 run_dir 기준으로 풀린다. `env`는 보간 변수로, env_file보다 우선한다.
    결과 파일에는 보간된 비밀 값이 들어갈 수 있어 0600으로 쓴다.
    """
    args = ["compose", "-p", project, "--project-directory", str(run_dir)]
    for f in compose_files:
        args += ["-f", str(f)]
    if env_file:
        args += ["--env-file", str(env_file)]
    r = _docker(*args, "config", "--format", "json", env={**os.environ, **(env or {})})
    if r.returncode:
        raise IsolationError(f"compose 설정을 해석하지 못함: {r.stderr.strip()}")
    config = json.loads(r.stdout)
    if bad := violations(config, run_dir):
        raise IsolationError("격리 규칙 위반:\n- " + "\n- ".join(bad))
    out = run_dir / "compose.wetrun.json"
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(sanitize(config, project, mem_limit), f, indent=2)
    return out


def check_user() -> str:
    """검사 컨테이너 사용자. 실행 디렉터리의 0600 파일(step.json)을 읽고 out/에 쓸 수 있게
    실행기와 같은 uid로 띄운다. root로 실행되면 검사까지 root가 되지 않게 nobody로 낮춘다.

    ponytail: root 실행 시 실행기가 step.json·out/을 65534로 chown해야 한다.
    """
    uid = os.getuid()
    return "65534:65534" if uid == 0 else f"{uid}:{os.getgid()}"


def hardening_args(
    project: str, network: str, memory: str = "512m", cpus: str = "1", pids: int = 256
) -> list[str]:
    """wetrun이 직접 띄우는 컨테이너(검사 등)용 `docker run` 옵션.

    ponytail: 자원 기본값은 임시. 검사 컨테이너 계약에서 확정한다.
    """
    return [
        "--label", f"{RUN_LABEL}={project}",
        "--network", network,
        "--read-only",
        "--tmpfs", "/tmp",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--user", check_user(),
        "--memory", memory,
        "--cpus", cpus,
        "--pids-limit", str(pids),
    ]  # fmt: skip


def resources(project: str) -> dict[str, list[str]]:
    """프로젝트 라벨이 붙은 컨테이너·네트워크·볼륨."""
    found = {}
    for kind, cmd in (
        ("container", ["ps", "-aq"]),
        ("network", ["network", "ls", "-q"]),
        ("volume", ["volume", "ls", "-q"]),
    ):
        ids: set[str] = set()
        for label in (COMPOSE_LABEL, RUN_LABEL):
            r = _docker(*cmd, "--filter", f"label={label}={project}")
            if r.returncode:
                raise IsolationError(f"Docker 자원을 조회하지 못함: {r.stderr.strip()}")
            ids.update(r.stdout.split())
        found[kind] = sorted(ids)
    return found


def ensure_visible(run_dir: Path) -> None:
    """Docker가 실행 디렉터리를 실제로 보는지 확인한다.

    Docker가 VM 안에서 도는 환경(Colima, Docker Desktop)은 공유하지 않은 호스트 경로를
    마운트하면 오류 없이 빈 폴더를 넣는다. 그러면 복원한 데이터가 서비스에 보이지 않아
    정상 백업이 fail로 잘못 판정된다.
    """
    marker = run_dir / ".wetrun-visible"
    marker.write_text(run_dir.name)
    r = _docker(
        "run", "--rm", "--network", "none", "--label", f"{RUN_LABEL}={run_dir.name}",
        "-v", f"{run_dir.resolve()}:/d:ro", CLEANUP_IMAGE, "cat", "/d/.wetrun-visible",
    )  # fmt: skip
    marker.unlink()
    if r.returncode or r.stdout.strip() != run_dir.name:
        raise IsolationError(
            f"Docker가 실행 디렉터리를 볼 수 없음: {run_dir}. "
            "Docker와 공유된 경로를 WETRUN_WORKDIR로 지정해야 함"
        )


def ensure_unused(project: str) -> None:
    if any(resources(project).values()):
        raise IsolationError(f"프로젝트 {project}의 자원이 이미 있음. 다른 실행과 겹침")


def cleanup(project: str, run_dir: Path | None = None) -> list[str]:
    """이번 실행이 만든 자원과 실행 디렉터리를 지운다. 실패해도 예외 없이 오류 목록을 돌려준다."""
    if not _PROJECT_RE.match(project):
        return [f"정리 거부: wetrun 프로젝트 이름이 아님 ({project!r})"]
    errors = []
    try:
        found = resources(project)
    except IsolationError as e:
        return [str(e)]
    for kind, rm in (
        ("container", ["rm", "-f", "-v"]),
        ("network", ["network", "rm"]),
        ("volume", ["volume", "rm", "-f"]),
    ):
        if found[kind]:
            r = _docker(*rm, *found[kind])
            if r.returncode:
                errors.append(f"{kind} 삭제 실패: {r.stderr.strip()}")
    if run_dir is not None:
        errors += _remove_run_dir(run_dir, project)
    try:
        left = resources(project)
    except IsolationError as e:
        return [*errors, str(e)]
    if any(left.values()):
        errors.append(f"정리 후 남은 자원: {left}")
    return errors


def _remove_run_dir(run_dir: Path, project: str) -> list[str]:
    if run_dir.name != project:
        return [f"정리 거부: 실행 디렉터리 이름이 프로젝트와 다름 ({run_dir})"]
    if not run_dir.exists():
        return []
    try:
        shutil.rmtree(run_dir)
        return []
    except OSError:
        pass
    # 컨테이너가 다른 uid로 만든 파일은 사용자 권한으로 못 지운다. 컨테이너 안에서 비운다.
    r = _docker(
        "run", "--rm", "--network", "none", "-v", f"{run_dir.resolve()}:/d",
        CLEANUP_IMAGE, "sh", "-c", "rm -rf /d/* /d/.[!.]* /d/..?*",
    )  # fmt: skip
    try:
        shutil.rmtree(run_dir)
        return []
    except OSError as e:
        detail = r.stderr.strip() if r.returncode else str(e)
        return [f"실행 디렉터리 삭제 실패: {run_dir}: {detail}"]


def _docker(*args: str, env: dict | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=False, env=env)
