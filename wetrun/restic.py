"""restic CLI 어댑터: 스냅샷 선택, 복원 전 확인, 복원.

판정 기준(#13): 원인이 백업 내용이면 FAIL, 실행 환경이나 입력이면 ERROR.
restic은 데이터 손상과 환경 문제를 둘 다 종료 코드 1로 내므로, 복원 전에 환경 원인
(저장소 접근, 비밀번호, 디스크 공간)을 먼저 확인하고, 그 뒤의 복원 실패를 FAIL로 본다.

비밀번호는 명령 인자가 아니라 환경 변수(RESTIC_PASSWORD)로 넘긴다. 인자는 ps에 보인다.
"""

import json
import os
import shutil
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


class Restic:
    def __init__(self, repository: str, password: str | None = None):
        self.env = {**os.environ, "RESTIC_REPOSITORY": repository}
        if password is not None:
            self.env["RESTIC_PASSWORD"] = password

    def find_snapshot(self, tag: str, select: str = "latest") -> dict:
        """태그가 붙은 스냅샷 중 `latest`(가장 최근) 또는 ID가 `select`로 시작하는 것.

        맞는 스냅샷이 없으면 FAIL: 검증할 백업이 없다는 뜻이다.
        """
        snaps = json.loads(self._run("snapshots", "--json", "--tag", tag).stdout or "[]")
        if select != "latest":
            snaps = [s for s in snaps if s["id"].startswith(select)]
        if not snaps:
            raise ResticError(
                Status.FAIL, f"스냅샷이 없음 (tag={tag}, select={select})", {"tag": tag}
            )
        return max(snaps, key=lambda s: s["time"])

    def restore_size(self, snapshot_id: str) -> int:
        out = self._run("stats", "--json", "--mode", "restore-size", snapshot_id).stdout
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
            r = subprocess.run(
                ["restic", *args],
                env=self.env,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError as e:
            raise ResticError(Status.ERROR, "restic이 설치되어 있지 않음") from e
        except subprocess.TimeoutExpired as e:
            raise ResticError(Status.ERROR, f"restic {args[0]} 시간 초과 ({timeout}초)") from e
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


def _existing_parent(path: Path) -> Path:
    while not path.exists():
        path = path.parent
    return path
