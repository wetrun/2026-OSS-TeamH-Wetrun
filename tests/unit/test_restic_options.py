"""원격 저장소용 restic 호출 옵션 (실제 restic 없이 명령 인자만 본다)."""

import subprocess
import time

import pytest

from wetrun import restic
from wetrun.contract import Status
from wetrun.restic import Restic, ResticError


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def fake_run(cmd, env, timeout):
        seen.append((cmd, timeout))
        return subprocess.CompletedProcess(cmd, 0, stdout="[]", stderr="")

    monkeypatch.setattr(restic, "_run_killing_group", fake_run)
    return seen


def test_read_only_uses_no_lock_and_sftp_never_prompts(calls):
    with pytest.raises(ResticError):  # 가짜 restic이 빈 목록을 돌려줘서 스냅샷 없음
        Restic("sftp:host:/repo", "pw", read_only=True, timeout=30).find_snapshot("t")
    cmd, timeout = calls[0]
    assert cmd[:4] == ["restic", "--no-lock", "-o", "sftp.args=-o BatchMode=yes"]
    assert timeout == 30  # 복원 전 확인에도 시간 제한


def test_local_repo_keeps_lock_and_no_ssh_options(calls):
    with pytest.raises(ResticError):
        Restic("/backup/repo", "pw").find_snapshot("t")
    assert calls[0][0][:2] == ["restic", "snapshots"]


def test_unresponsive_repo_is_error_and_marked_timed_out(monkeypatch):
    def hang(cmd, env, timeout):
        raise subprocess.TimeoutExpired(cmd, timeout)

    monkeypatch.setattr(restic, "_run_killing_group", hang)
    with pytest.raises(ResticError) as e:
        Restic("sftp:host:/repo", "pw", timeout=5).find_snapshot("t")
    assert e.value.status == Status.ERROR and e.value.timed_out


def test_timeout_kills_children_too(tmp_path):
    """restic이 띄운 ssh처럼 자식 프로세스가 남지 않는다."""
    marker = tmp_path / "child-alive"
    # setsid 없이도, 자식이 따로 세션을 만들어도(restic의 ssh처럼) 끊겨야 한다
    cmd = ["python3", "-c",
           "import os,subprocess,time;"
           f"subprocess.Popen(['sh','-c','sleep 3; touch {marker}'],start_new_session=True);"
           "time.sleep(30)"]  # fmt: skip
    with pytest.raises(subprocess.TimeoutExpired):
        restic._run_killing_group(cmd, {}, timeout=1)
    time.sleep(3)
    assert not marker.exists()
