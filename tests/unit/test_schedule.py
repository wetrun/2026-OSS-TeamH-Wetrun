import os
import subprocess
import sys

import pytest

from wetrun.schedule import ScheduleError, cron_line


def test_cron_line_runs_daily_with_env_and_log(tmp_path):
    wf = tmp_path / "workflow.yaml"
    wf.write_text("")
    env = tmp_path / "wetrun.env"
    env.write_text("RESTIC_PASSWORD=x\n")
    env.chmod(0o600)
    line = cron_line(wf, "03:05", env, tmp_path / "data")
    assert line.startswith("5 3 * * * umask 077 && export PATH=")  # 로그를 본인만 읽게
    assert f". {env}" in line and f"-m wetrun run {wf}" in line
    assert f">> {tmp_path / 'data' / 'cron.log'} 2>&1" in line


def test_cron_line_runs_in_sh(tmp_path):
    # 만든 줄의 명령 부분이 sh에서 그대로 돈다 (wetrun run → 입력 오류 종료 코드 2)
    wf = tmp_path / "workflow.yaml"
    wf.write_text("version: 1\n")
    env = tmp_path / "wetrun.env"
    env.write_text("WETRUN_X=1\n")
    env.chmod(0o600)
    (tmp_path / "data").mkdir()
    command = cron_line(wf, "00:00", env, tmp_path / "data").split(" ", 5)[5]
    r = subprocess.run(["sh", "-c", command.replace(r"\%", "%")], env={**os.environ})
    assert r.returncode == 2
    assert "필수 키가 없음" in (tmp_path / "data" / "cron.log").read_text()


def test_cron_line_rejects_bad_input(tmp_path):
    wf = tmp_path / "workflow.yaml"
    wf.write_text("")
    env = tmp_path / "wetrun.env"
    env.write_text("")
    env.chmod(0o644)
    for args, expected in [
        ((wf, "3:5", None), "HH:MM"),
        ((wf, "24:00", None), "HH:MM"),
        ((tmp_path / "nope.yaml", "03:00", None), "워크플로가 없음"),
        ((wf, "03:00", env), "chmod 600"),
    ]:
        with pytest.raises(ScheduleError, match=expected):
            cron_line(*args, tmp_path)


def test_schedule_cli_prints_line(tmp_path):
    wf = tmp_path / "workflow.yaml"
    wf.write_text("")
    r = subprocess.run(
        [sys.executable, "-m", "wetrun", "schedule", str(wf), "--at", "04:00"],
        capture_output=True, text=True, env={**os.environ, "WETRUN_REPORT_DIR": str(tmp_path)},
    )  # fmt: skip
    assert r.returncode == 0 and "0 4 * * *" in r.stdout
