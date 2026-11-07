"""실제 Docker로 격리·정리를 확인한다. Docker가 없으면 건너뛴다."""

import shutil
import subprocess

import pytest

from wetrun import isolation as iso

pytestmark = pytest.mark.skipif(
    shutil.which("docker") is None
    or subprocess.run(["docker", "info"], capture_output=True).returncode != 0,
    reason="Docker 필요",
)

# 운영 Immich처럼 고정 container_name·공개 포트·bind·named volume을 쓰는 서비스.
# 컨테이너가 root로 bind 디렉터리에 파일을 만들어 정리 fallback도 확인한다.
COMPOSE = """
services:
  app:
    image: alpine:3
    command: ["sh", "-c", "touch /data/root-owned && sleep 300"]
    container_name: wetrun-test-prod
    ports: ["127.0.0.1:18765:80"]
    volumes: ["./data:/data", "cache:/cache"]
volumes:
  cache: {}
"""


def docker(*args):
    return subprocess.run(["docker", *args], capture_output=True, text=True)


@pytest.fixture
def prod():
    """같은 container_name·포트를 이미 쓰는 '운영' 컨테이너와 다른 프로젝트의 볼륨."""
    docker("rm", "-f", "wetrun-test-prod")
    docker("volume", "rm", "-f", "wetrun-test-prod-vol")
    r = docker("run", "-d", "--name", "wetrun-test-prod", "-p", "127.0.0.1:18765:80",
               "alpine:3", "sleep", "300")  # fmt: skip
    assert r.returncode == 0, r.stderr
    docker("volume", "create", "--label", f"{iso.COMPOSE_LABEL}=prod", "wetrun-test-prod-vol")
    yield
    docker("rm", "-f", "wetrun-test-prod")
    docker("volume", "rm", "-f", "wetrun-test-prod-vol")


def test_isolated_run_then_cleanup_leaves_nothing(tmp_path, prod):
    project = iso.project_name(iso.new_run_id())
    run_dir = iso.make_run_dir(tmp_path, project)
    try:
        iso.ensure_unused(project)
        (run_dir / "compose.yaml").write_text(COMPOSE)
        compose = iso.prepare([run_dir / "compose.yaml"], run_dir, project)

        up = docker("compose", "-p", project, "-f", str(compose), "up", "-d")
        assert up.returncode == 0, up.stderr  # 운영과 이름·포트가 겹치지 않아야 기동됨

        found = iso.resources(project)
        assert found["container"] and found["network"] and found["volume"]
        for net in found["network"]:
            assert docker("network", "inspect", "-f", "{{.Internal}}", net).stdout.strip() == "true"
        ports = docker("ps", "--filter", f"label={iso.COMPOSE_LABEL}={project}",
                       "--format", "{{.Ports}}")  # fmt: skip
        assert ports.stdout.strip() == ""
    finally:
        errors = iso.cleanup(project, run_dir)

    assert errors == []
    assert iso.resources(project) == {"container": [], "network": [], "volume": []}
    assert not run_dir.exists()
    assert docker("inspect", "wetrun-test-prod").returncode == 0  # 운영 컨테이너 보존
    assert docker("volume", "inspect", "wetrun-test-prod-vol").returncode == 0


def test_prepare_rejects_bind_outside_run_dir(tmp_path):
    project = iso.project_name(iso.new_run_id())
    run_dir = iso.make_run_dir(tmp_path, project)
    (run_dir / "compose.yaml").write_text(
        "services:\n  app:\n    image: alpine:3\n    volumes: ['/etc:/host-etc:ro']\n"
    )
    with pytest.raises(iso.IsolationError, match="실행 디렉터리 밖"):
        iso.prepare([run_dir / "compose.yaml"], run_dir, project)
    assert iso.cleanup(project, run_dir) == []
