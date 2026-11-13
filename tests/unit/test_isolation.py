from pathlib import Path
from unittest import mock

from wetrun.isolation import check_user, sanitize, violations

RUN = Path("/run/wetrun-x")


def svc(**spec) -> dict:
    return {"services": {"app": {"image": "alpine:3", **spec}}}


def test_clean_config_has_no_violations():
    bind = {"type": "bind", "source": str(RUN / "data"), "target": "/data"}
    tz = {"type": "bind", "source": "/etc/localtime", "target": "/etc/localtime", "read_only": True}
    assert violations(svc(volumes=[bind, tz]), RUN) == []


def test_rejects_escape_routes():
    bad = [
        svc(privileged=True),
        svc(devices=["/dev/sda:/dev/sda"]),
        svc(network_mode="host"),
        svc(pid="host"),
        svc(uts="host"),
        svc(userns_mode="host"),
        svc(volumes=[{"type": "bind", "source": "/var/run/docker.sock", "target": "/s"}]),
        svc(volumes=[{"type": "bind", "source": "/etc", "target": "/e"}]),
        svc(volumes=[{"type": "bind", "source": "/etc/localtime", "target": "/t"}]),  # 쓰기 가능
        svc(volumes=[{"type": "bind", "source": str(RUN / "../other"), "target": "/o"}]),
        {**svc(), "volumes": {"v": {"external": True}}},
        {**svc(), "secrets": {"s": {"file": "/etc/shadow"}}},
        {**svc(), "configs": {"c": {"file": "/etc/passwd"}}},
    ]
    for config in bad:
        assert violations(config, RUN), config


def test_sanitize_removes_overlap_and_isolates_network():
    out = sanitize(svc(container_name="prod", ports=["2283:2283"]), "wetrun-x")
    app = out["services"]["app"]
    assert "container_name" not in app and "ports" not in app
    assert app["labels"]["wetrun.project"] == "wetrun-x"
    assert out["networks"] == {"default": {"internal": True}}


def test_check_user_matches_runner_but_never_root():
    with mock.patch("os.getuid", return_value=1000), mock.patch("os.getgid", return_value=1000):
        assert check_user() == "1000:1000"
    with mock.patch("os.getuid", return_value=0):
        assert check_user() == "65534:65534"


def test_sanitize_caps_memory_per_service():
    config = {
        "services": {
            "a": {"image": "x"},
            "b": {"image": "x", "mem_limit": "512m"},
            "c": {"image": "x", "deploy": {"resources": {"limits": {"memory": "1g"}}}},
        }
    }
    out = sanitize(config, "wetrun-x")["services"]
    assert out["a"]["mem_limit"] == "2g"  # 기본 상한
    assert out["b"]["mem_limit"] == "512m" and "mem_limit" not in out["c"]  # compose 값 유지
    assert sanitize(config, "wetrun-x", "3g")["services"]["b"]["mem_limit"] == "3g"
    per = sanitize(config, "wetrun-x", {"a": "1g"})["services"]
    assert per["a"]["mem_limit"] == "1g" and per["b"]["mem_limit"] == "512m"
