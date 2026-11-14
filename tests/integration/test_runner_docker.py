"""실제 restic·Docker로 복원 → 기동 → 검사 → 정리를 끝까지 돌린다. 없으면 건너뛴다."""

import json
import os
import shutil
import subprocess

import pytest
import yaml

from wetrun import isolation as iso
from wetrun import runner
from wetrun.contract import EXIT_FAIL, EXIT_PASS, Status, exit_code

pytestmark = pytest.mark.skipif(
    shutil.which("restic") is None
    or shutil.which("docker") is None
    or subprocess.run(["docker", "info"], capture_output=True).returncode != 0,
    reason="restic·Docker 필요",
)

COMPOSE = """
services:
  web:
    image: python:3.12-slim
    command: ["python", "-m", "http.server", "8000", "-d", "/srv"]
    volumes: ["${SITE}:/srv:ro"]
    container_name: wetrun-test-prod-web
    ports: ["127.0.0.1:18766:8000"]
"""
SCRIPT_PASS = 'echo \'{"status":"pass","message":"ok","evidence":{}}\' > /wetrun/out/result.json'


@pytest.fixture
def setup(tmp_path, monkeypatch):
    src = tmp_path / "src"
    (src / "data").mkdir(parents=True)
    (src / "data" / "hello.txt").write_text("hello")
    env = {**os.environ, "RESTIC_REPOSITORY": str(tmp_path / "repo"), "RESTIC_PASSWORD": "pw"}
    for cmd in (["init"], ["backup", "--tag", "svc", "data"]):
        subprocess.run(["restic", "-q", *cmd], cwd=src, env=env, check=True)
    (tmp_path / "docker-compose.yml").write_text(COMPOSE)
    monkeypatch.setenv("WETRUN_TEST_PW", "pw")
    # Docker가 VM에서 돌면(Colima 등) 공유된 경로여야 한다. 그때는 WETRUN_WORKDIR로 지정
    if "WETRUN_WORKDIR" not in os.environ:
        if not docker_sees(tmp_path):
            pytest.skip("Docker가 임시 폴더를 볼 수 없음. 공유된 경로를 WETRUN_WORKDIR로 지정")
        monkeypatch.setattr(runner, "WORK_BASE", tmp_path / "work")

    def write(steps):
        wf = {
            "version": 1,
            "repository": {"path": "repo", "password": "env:WETRUN_TEST_PW"},
            "snapshot": {"tag": "svc"},
            "compose": {"files": ["docker-compose.yml"], "env": {"SITE": "{restore}/data"}},
            "steps": steps,
        }
        path = tmp_path / "workflow.yaml"
        path.write_text(yaml.safe_dump(wf))
        return path

    return write


def leftovers(result) -> dict:
    return iso.resources(iso.project_name(result.run_id))


def test_healthy_backup_passes(setup):
    result = runner.run(
        setup(
            [
                {"use": "restore"},
                {"use": "up"},
                {
                    "use": "exec",
                    "service": "web",
                    "command": ["sh", "-c", "cat > /dev/null"],
                    "stdin": "{restore}/data/hello.txt",
                },
                {"use": "http", "url": "http://web:8000/hello.txt", "timeout": 30},
                {"use": "script", "image": "alpine:3", "command": ["sh", "-c", SCRIPT_PASS]},
            ]
        )
    )
    print(json.dumps([s.__dict__ for s in result.steps], ensure_ascii=False, default=str))
    assert [s.status for s in result.steps] == [Status.PASS] * 5
    assert result.snapshot_id and exit_code(result) == EXIT_PASS
    # 실행 이력용 값 (계약 6절)
    assert result.workflow_id and result.snapshot_time and result.warnings == []
    assert result.memory_peak_bytes.get("web", 0) > 0
    assert not any(s.timed_out for s in result.steps)
    assert not result.cleanup_errors and not any(leftovers(result).values())


def test_missing_data_fails_and_skips_rest(setup):
    result = runner.run(
        setup(
            [
                {"use": "restore"},
                {"use": "up"},
                {"use": "http", "url": "http://web:8000/missing.txt", "timeout": 5},
                {"use": "script", "image": "alpine:3", "command": ["sh", "-c", SCRIPT_PASS]},
            ]
        )
    )
    assert [s.status for s in result.steps][2:] == [Status.FAIL, Status.SKIPPED]
    assert exit_code(result) == EXIT_FAIL
    assert not any(leftovers(result).values())


def docker_sees(path) -> bool:
    try:
        iso.ensure_visible(path)
        return True
    except iso.IsolationError:
        return False


def test_unshared_workdir_is_error_not_fail(tmp_path, monkeypatch):
    if docker_sees(tmp_path):
        pytest.skip("Docker가 모든 경로를 봄 (Linux)")
    monkeypatch.setattr(runner, "WORK_BASE", tmp_path)
    wf = tmp_path / "w.yaml"
    (tmp_path / "c.yml").write_text("services: {}")
    wf.write_text(yaml.safe_dump({
        "version": 1, "repository": {"path": "sftp:x"}, "snapshot": {"tag": "t"},
        "compose": {"files": ["c.yml"]}, "steps": [{"use": "restore"}],
    }))  # fmt: skip
    with pytest.raises(iso.IsolationError, match="볼 수 없음"):
        runner.run(wf)
    assert not list(tmp_path.glob("wetrun-*"))  # 실행 디렉터리도 정리됨


HOG = """
services:
  hog:
    image: python:3.12-slim
    command: ["python", "-c", "b = bytearray(300 * 1024 * 1024); import time; time.sleep(60)"]
"""


def test_oom_is_error_not_fail(tmp_path, monkeypatch):
    """메모리 상한을 넘겨 죽은 서비스는 백업 문제(fail)가 아니라 환경 문제(error)다."""
    if "WETRUN_WORKDIR" not in os.environ:
        if not docker_sees(tmp_path):
            pytest.skip("Docker가 임시 폴더를 볼 수 없음. 공유된 경로를 WETRUN_WORKDIR로 지정")
        monkeypatch.setattr(runner, "WORK_BASE", tmp_path / "work")
    (tmp_path / "c.yml").write_text(HOG)
    wf = tmp_path / "w.yaml"
    wf.write_text(yaml.safe_dump({
        "version": 1, "repository": {"path": "sftp:x"}, "snapshot": {"tag": "t"},
        "compose": {"files": ["c.yml"], "mem_limit": {"hog": "64m"}},
        "steps": [{"use": "up", "timeout": 60}],
    }))  # fmt: skip
    result = runner.run(wf)
    step = result.steps[0]
    assert step.status == Status.ERROR and "메모리" in step.message, step
    assert not any(leftovers(result).values())


SLOW = """
services:
  slow:
    image: alpine:3
    command: ["sleep", "300"]
    healthcheck:
      test: ["CMD", "false"]
      interval: 1s
      start_period: 300s
"""


def test_service_not_healthy_by_deadline_is_fail(tmp_path, monkeypatch):
    """마감까지 healthy가 되지 못한 서비스는 복구 문제(fail)다. Compose 버전과 상관없이."""
    if "WETRUN_WORKDIR" not in os.environ:
        if not docker_sees(tmp_path):
            pytest.skip("Docker가 임시 폴더를 볼 수 없음. 공유된 경로를 WETRUN_WORKDIR로 지정")
        monkeypatch.setattr(runner, "WORK_BASE", tmp_path / "work")
    (tmp_path / "c.yml").write_text(SLOW)
    wf = tmp_path / "w.yaml"
    wf.write_text(yaml.safe_dump({
        "version": 1, "repository": {"path": "sftp:x"}, "snapshot": {"tag": "t"},
        "compose": {"files": ["c.yml"]}, "steps": [{"use": "up", "timeout": 8}],
    }))  # fmt: skip
    result = runner.run(wf)
    step = result.steps[0]
    assert step.status == Status.FAIL and "8초 안에" in step.message, step
    assert step.timed_out  # 이력 계산에서 빼야 하는 표본
    assert step.evidence["containers"][0]["health"] == "starting"
    assert not any(leftovers(result).values())


def test_memory_shortfall_from_history_is_error_before_start(tmp_path, monkeypatch):
    """지난 실행의 최대 메모리로 봐서 빈 메모리가 모자라면 띄우지 않고 error (계약 6절)."""
    if "WETRUN_WORKDIR" not in os.environ:
        if not docker_sees(tmp_path):
            pytest.skip("Docker가 임시 폴더를 볼 수 없음. 공유된 경로를 WETRUN_WORKDIR로 지정")
        monkeypatch.setattr(runner, "WORK_BASE", tmp_path / "work")
    (tmp_path / "c.yml").write_text(
        "services:\n  app:\n    image: alpine:3\n    command: [sleep, '300']\n"
    )
    wf = tmp_path / "w.yaml"
    wf.write_text(yaml.safe_dump({
        "version": 1, "repository": {"path": "sftp:x"}, "snapshot": {"tag": "t"},
        "compose": {"files": ["c.yml"]}, "steps": [{"use": "up", "timeout": 30}],
    }))  # fmt: skip
    history = [{"memory_peak_bytes": {"app": 10**15}}]  # 1PB: 어떤 컴퓨터에도 없는 양
    step = runner.run(wf, history).steps[0]
    assert step.status == Status.ERROR and "메모리 부족 예상" in step.message, step
    assert step.evidence["services"] == ["app"]
    # 이력이 없으면 확인하지 않고 그대로 띄운다
    result = runner.run(wf)
    assert result.steps[0].status == Status.PASS
    assert not any(leftovers(result).values())
