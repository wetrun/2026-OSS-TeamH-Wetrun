import subprocess
import sys

import yaml


def test_help_runs():
    r = subprocess.run([sys.executable, "-m", "wetrun", "--help"], capture_output=True)
    assert r.returncode == 0


def test_run_with_bad_workflow_fails_before_starting():
    r = subprocess.run([sys.executable, "-m", "wetrun", "run", "x.yaml"], capture_output=True)
    assert r.returncode == 2


def test_check_input_reports_problems(tmp_path):
    bad = tmp_path / "w.yaml"
    bad.write_text("version: 1\nsteps: [{use: nope}]\n")
    r = subprocess.run(
        [sys.executable, "-m", "wetrun", "check-input", str(bad)], capture_output=True, text=True
    )
    assert r.returncode == 2
    assert "모르는 use" in r.stderr and "repository: 필수 키가 없음" in r.stderr


def _fake_run(monkeypatch, tmp_path, workflow_text: str):
    """runner.run을 가짜로 바꿔 Docker 없이 `wetrun run`의 출력 경로만 시험한다."""
    from wetrun import __main__ as cli
    from wetrun import notify, runner
    from wetrun.contract import RunResult, Status, StepResult

    path = tmp_path / "svc" / "workflow.yaml"
    path.parent.mkdir()
    path.write_text(workflow_text)
    result = RunResult(
        "r1", "abcdef12", "0" * 64, "t", 1.0,
        [StepResult("restore", "restore", Status.FAIL, message="pw=topsecret")],
    )  # fmt: skip
    monkeypatch.setattr(runner, "run", lambda p: result)
    # 파일 존재 확인 없이 읽기만 한다 (실제 load는 test_workflow.py가 시험)
    monkeypatch.setattr(cli, "load", lambda p: yaml.safe_load(p.read_text()))
    sent = {}

    def fake_send(*args, **kwargs):
        sent.update(args=args, kw=kwargs)
        return True, "보냄"

    monkeypatch.setattr(notify, "send", fake_send)
    return cli, path, sent


def test_run_saves_report_prints_summary_and_notifies(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("WETRUN_TEST_PW", "topsecret")
    monkeypatch.setenv("WETRUN_TEST_HOOK", "https://discord.test/hook")
    monkeypatch.setenv("WETRUN_REPORT_DIR", str(tmp_path / "runs"))
    cli, path, sent = _fake_run(
        monkeypatch,
        tmp_path,
        "repository: {password: env:WETRUN_TEST_PW}\nnotify: {discord: env:WETRUN_TEST_HOOK}\n",
    )
    assert cli.main(["run", str(path)]) == 1
    out = capsys.readouterr().out
    assert "Wetrun 결과: FAIL" in out and "리포트:" in out
    assert "topsecret" not in out and "pw=***" in out
    report_file = tmp_path / "runs" / "r1.json"
    assert "topsecret" not in report_file.read_text()
    assert sent["args"][0] == "https://discord.test/hook"
    assert sent["kw"]["title"] == "svc" and sent["kw"]["report_path"] == str(report_file)


def test_report_save_failure_keeps_exit_code(monkeypatch, tmp_path, capsys):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("")  # 폴더 자리에 파일이 있어 저장이 실패한다
    monkeypatch.setenv("WETRUN_REPORT_DIR", str(blocker / "runs"))
    cli, path, sent = _fake_run(monkeypatch, tmp_path, "steps: []\n")
    assert cli.main(["run", str(path)]) == 1  # fail 판정 그대로. 파이썬 예외(1)가 아니다
    captured = capsys.readouterr()
    assert "리포트를 저장하지 못함" in captured.err
    assert "Wetrun 결과: FAIL" in captured.out and "리포트:" not in captured.out
    assert sent == {}  # notify 설정이 없으면 보내지 않는다


def test_service_name():
    from pathlib import Path

    from wetrun.__main__ import service_name

    assert service_name(Path("profiles/svc/workflow.yaml")) == "svc"
    assert service_name(Path("/etc/wetrun/photos.yaml")) == "photos"
