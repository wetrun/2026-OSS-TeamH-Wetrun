import subprocess
import sys


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
