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


def test_root_owned_files_restore_as_user(tmp_path):
    """서비스 컨테이너가 root로 만든 파일(예: 업로드한 사진)이 든 백업도 일반 사용자로 복원된다.

    restic은 일반 사용자일 때 소유자 복원 실패를 오류로 보지 않는다. 대신 파일 소유자는
    복원한 사용자가 된다. Linux에서만 의미가 있다 (macOS Docker는 소유자를 바꿔 보여 준다).
    """
    if os.getuid() == 0 or shutil.which("docker") is None:
        pytest.skip("일반 사용자와 Docker 필요")
    src = tmp_path / "src"
    (src / "data").mkdir(parents=True)
    subprocess.run(
        ["docker", "run", "--rm", "-v", f"{src / 'data'}:/d", "alpine:3",
         "sh", "-c", "echo photo > /d/root.jpg"],
        check=True, capture_output=True,
    )  # fmt: skip
    made = src / "data" / "root.jpg"
    if not made.exists() or made.stat().st_uid != 0:
        pytest.skip("Docker가 이 경로에 root 소유 파일을 만들지 못함 (macOS 등)")
    env = {**os.environ, "RESTIC_REPOSITORY": str(tmp_path / "repo"), "RESTIC_PASSWORD": PW}
    for cmd in (["init"], ["backup", "--tag", "svc", "data"]):
        subprocess.run(["restic", "-q", *cmd], cwd=src, env=env, check=True)

    r = Restic(str(tmp_path / "repo"), PW)
    snap = r.preflight("svc", "latest", tmp_path / "out")
    r.restore(snap["id"], tmp_path / "out")  # 소유자 복원 실패로 fail이 되지 않아야 한다
    restored = tmp_path / "out" / "data" / "root.jpg"
    assert restored.read_text() == "photo\n"
    assert restored.stat().st_uid == os.getuid()
    # 테스트가 만든 root 소유 원본 정리
    subprocess.run(["docker", "run", "--rm", "-v", f"{src}:/s", "alpine:3", "rm", "-rf", "/s/data"],
                   capture_output=True)  # fmt: skip
