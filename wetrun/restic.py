"""restic CLI 어댑터: 스냅샷 선택, 복원 전 확인, 복원.

판정 기준(#13): 원인이 백업 내용이면 FAIL, 실행 환경이나 입력이면 ERROR.
restic은 데이터 손상과 환경 문제를 둘 다 종료 코드 1로 내므로, 복원 전에 환경 원인
(저장소 접근, 비밀번호, 디스크 공간)을 먼저 확인하고, 그 뒤의 복원 실패를 FAIL로 본다.

비밀번호는 명령 인자가 아니라 환경 변수(RESTIC_PASSWORD)로 넘긴다. 인자는 ps에 보인다.
"""

import contextlib
import json
import os
import shutil
import signal
import subprocess
from pathlib import Path

from wetrun.contract import Status

# restic 0.17+ 종료 코드 (0.19.1에서 확인)
EXIT_NO_REPO, EXIT_LOCKED, EXIT_WRONG_PASSWORD, EXIT_INTERRUPTED = 10, 11, 12, 130
_ENV_EXITS = {
    EXIT_NO_REPO: "저장소가 없음",
    EXIT_LOCKED: "저장소가 잠겨 있음 (다른 restic 작업 중)",
    EXIT_WRONG_PASSWORD: "비밀번호가 틀림",
    EXIT_INTERRUPTED: "중단됨",
}
STDERR_LINES = 20


class ResticError(Exception):
    def __init__(self, status: Status, message: str, evidence: dict | None = None):
        super().__init__(message)
        self.status, self.message, self.evidence = status, message, evidence or {}
        self.timed_out = False


class Restic:
    def __init__(
        self,
        repository: str,
        password: str | None = None,
        read_only: bool = False,
        timeout: float | None = None,
    ):
        """read_only: 잠금 파일을 쓰지 않는다(--no-lock). 검증 계정에 읽기 권한만 줄 수 있다.
        timeout: 복원 전 확인(스냅샷 목록, 복원 크기) 명령마다 적용. 원격 저장소가 응답하지
        않으면 restic은 몇 분 넘게 재시도하므로 끊어야 한다.
        """
        self.env = {**os.environ, "RESTIC_REPOSITORY": repository}
        if password is not None:
            self.env["RESTIC_PASSWORD"] = password
        self.timeout = timeout
        self.options = ["--no-lock"] if read_only else []
        if repository.startswith("sftp:"):
            # ssh가 비밀번호·호스트 키 확인을 물으며 멈추지 않고 바로 실패하게 한다
            self.options += ["-o", "sftp.args=-o BatchMode=yes"]

    def find_snapshot(self, tag: str, select: str = "latest") -> dict:
        """태그가 붙은 스냅샷 중 `latest`(가장 최근) 또는 ID가 `select`로 시작하는 것.

        맞는 스냅샷이 없으면 FAIL: 검증할 백업이 없다는 뜻이다.
        """
        out = self._run("snapshots", "--json", "--tag", tag, timeout=self.timeout).stdout
        snaps = json.loads(out or "[]")
        if select != "latest":
            snaps = [s for s in snaps if s["id"].startswith(select)]
        if not snaps:
            raise ResticError(
                Status.FAIL, f"스냅샷이 없음 (tag={tag}, select={select})", {"tag": tag}
            )
        return max(snaps, key=lambda s: s["time"])

    def restore_size(self, snapshot_id: str) -> int:
        out = self._run(
            "stats", "--json", "--mode", "restore-size", snapshot_id, timeout=self.timeout
        ).stdout
        return json.loads(out)["total_size"]

    def preflight(self, tag: str, select: str, target: Path) -> dict:
        """복원 전 확인. 저장소·비밀번호 문제와 디스크 부족은 ERROR로 여기서 걸러진다."""
        snap = self.find_snapshot(tag, select)
        size = self.restore_size(snap["id"])
        free = shutil.disk_usage(_existing_parent(target)).free
        if free < size:
            raise ResticError(
                Status.ERROR,
                "디스크 공간 부족",
                {"snapshot_id": snap["id"], "restore_size": size, "free": free},
            )
        return {**snap, "restore_size": size}

    def restore(self, snapshot_id: str, target: Path, timeout: float | None = None) -> None:
        """preflight를 통과한 뒤에 부른다. 이때의 복원 실패는 백업 데이터 문제(FAIL)로 본다."""
        self._run("restore", snapshot_id, "--target", str(target), timeout=timeout, fail=True)

    def _run(self, *args: str, timeout: float | None = None, fail: bool = False):
        try:
            r = _run_killing_group(["restic", *self.options, *args], self.env, timeout)
        except FileNotFoundError as e:
            raise ResticError(Status.ERROR, "restic이 설치되어 있지 않음") from e
        except subprocess.TimeoutExpired as e:
            err = ResticError(Status.ERROR, f"restic {args[0]} 시간 초과 ({timeout}초)")
            err.timed_out = True
            raise err from e
        if r.returncode == 0:
            return r
        evidence = {
            "command": f"restic {args[0]}",
            "exit_code": r.returncode,
            "stderr": r.stderr.strip().splitlines()[-STDERR_LINES:],
        }
        if r.returncode in _ENV_EXITS or not fail:
            reason = _ENV_EXITS.get(r.returncode, "restic 실행 실패")
            raise ResticError(Status.ERROR, f"restic {args[0]}: {reason}", evidence)
        raise ResticError(Status.FAIL, f"restic {args[0]}: 백업 데이터를 복원하지 못함", evidence)


def _run_killing_group(cmd: list[str], env: dict, timeout: float | None):
    """subprocess.run과 같지만, 시간 초과 때 restic이 띄운 ssh 같은 자식 프로세스까지 끊는다."""
    p = subprocess.Popen(
        cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        start_new_session=True,
    )  # fmt: skip
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        # restic은 ssh를 별도 세션으로 띄워서 그룹째 끊어도 남는다. 자식을 찾아 같이 끊는다
        children = subprocess.run(
            ["pgrep", "-P", str(p.pid)], capture_output=True, text=True, check=False
        ).stdout.split()
        os.killpg(p.pid, signal.SIGKILL)
        for pid in children:
            with contextlib.suppress(ProcessLookupError, ValueError):
                os.kill(int(pid), signal.SIGKILL)
        p.communicate()
        raise
    return subprocess.CompletedProcess(cmd, p.returncode, out, err)


def _existing_parent(path: Path) -> Path:
    while not path.exists():
        path = path.parent
    return path
