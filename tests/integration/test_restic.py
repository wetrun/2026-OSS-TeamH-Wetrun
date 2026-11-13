"""실제 restic으로 판정 기준(#13)을 확인한다. restic이 없으면 건너뛴다."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from wetrun.contract import Status
from wetrun.restic import Restic, ResticError

pytestmark = pytest.mark.skipif(shutil.which("restic") is None, reason="restic 필요")
PW = "test-pw"


@pytest.fixture
def repo(tmp_path) -> Path:
    src, repo = tmp_path / "src", tmp_path / "repo"
    (src / "data").mkdir(parents=True)
    (src / "data" / "a.bin").write_bytes(os.urandom(256_000))  # 압축되지 않게
    env = {**os.environ, "RESTIC_REPOSITORY": str(repo), "RESTIC_PASSWORD": PW}
    for cmd in (["init"], ["backup", "--tag", "svc", "data"]):
        subprocess.run(["restic", "-q", *cmd], cwd=src, env=env, check=True)
    return repo


def status_of(fn) -> Status:
    with pytest.raises(ResticError) as e:
        fn()
    return e.value.status


def test_restore_ok(repo, tmp_path):
    r = Restic(str(repo), PW)
    snap = r.preflight("svc", "latest", tmp_path / "out")
    assert snap["restore_size"] > 0
    r.restore(snap["id"], tmp_path / "out")
    assert (tmp_path / "out" / "data" / "a.bin").stat().st_size == 256_000


def test_select_by_id_prefix(repo):
    r = Restic(str(repo), PW)
    snap = r.find_snapshot("svc")
    assert r.find_snapshot("svc", snap["id"][:8])["id"] == snap["id"]


def test_environment_problems_are_error(repo, tmp_path):
    assert status_of(lambda: Restic(str(repo), "wrong").find_snapshot("svc")) == Status.ERROR
    assert status_of(lambda: Restic(str(tmp_path / "nope"), PW).find_snapshot("svc")) == (
        Status.ERROR
    )


def test_missing_snapshot_is_fail(repo):
    assert status_of(lambda: Restic(str(repo), PW).find_snapshot("other")) == Status.FAIL


def test_corrupted_data_is_fail(repo, tmp_path):
    r = Restic(str(repo), PW)
    snap = r.preflight("svc", "latest", tmp_path / "out")
    for pack in (repo / "data").rglob("*"):
        if pack.is_file() and pack.stat().st_size > 10_000:
            pack.chmod(0o600)
            data = bytearray(pack.read_bytes())
            data[1000] ^= 0xFF
            pack.write_bytes(data)
    assert status_of(lambda: r.restore(snap["id"], tmp_path / "out")) == Status.FAIL
