import subprocess
import sys


def test_help_runs():
    r = subprocess.run([sys.executable, "-m", "wetrun", "--help"], capture_output=True)
    assert r.returncode == 0


def test_unimplemented_command_fails():
    r = subprocess.run([sys.executable, "-m", "wetrun", "run", "x.yaml"], capture_output=True)
    assert r.returncode == 2
