import json
from datetime import UTC

from wetrun.contract import Status, StepResult
from wetrun.runner import _check_result, _mask


def result_file(tmp_path, data):
    p = tmp_path / "result.json"
    p.write_text(json.dumps(data) if data is not None else "")
    return p


def test_check_result_needs_exit_code_and_status_to_agree(tmp_path):
    def status(code, data):
        return _check_result(code, result_file(tmp_path, data), "")[0]

    assert status(0, {"status": "pass"}) == Status.PASS
    assert status(1, {"status": "fail"}) == Status.FAIL
    assert status(2, {"status": "error", "message": "x"}) == Status.ERROR
    # 파이썬이 예외로 죽으면 1이지만 result.json이 없다 → fail이 아니라 error
    assert status(1, None) == Status.ERROR
    assert status(0, {"status": "fail"}) == Status.ERROR
    assert status(1, {"status": "pass"}) == Status.ERROR


def test_mask_hides_secrets_in_message_and_evidence():
    r = StepResult(
        "s", "http", Status.FAIL, message="login pw=hunter2", evidence={"a": ["hunter2"]}
    )
    _mask(r, {"hunter2"})
    assert "hunter2" not in json.dumps([r.message, r.evidence])


def test_mask_keeps_numbers_when_secret_is_digits():
    # #25: 숫자로만 된 비밀 값이 숫자 일부와 같아도 결과가 깨지지 않는다
    r = StepResult(
        "restore", "restore", Status.PASS, message="pw 5430", evidence={"bytes": 54305072}
    )
    _mask(r, {"5430"})
    assert r.evidence == {"bytes": 54305072} and r.message == "pw ***"


def test_stale_snapshot_warning():
    from datetime import datetime, timedelta

    from wetrun.runner import stale_snapshot_warning

    now = datetime(2026, 11, 14, tzinfo=UTC)
    # restic처럼 소수점 아래 9자리
    old = (now - timedelta(days=5)).isoformat().replace("+00:00", ".123456789+00:00")
    fresh = (now - timedelta(days=1)).isoformat()
    assert "5일 전" in stale_snapshot_warning(old, None, now)[0]  # 기본 3일
    assert stale_snapshot_warning(old, 7, now) == []
    assert stale_snapshot_warning(fresh, None, now) == []
    assert stale_snapshot_warning("", None, now) == []  # 복원 전에 멈춘 실행


def test_parse_bytes():
    from wetrun.runner import parse_bytes

    assert parse_bytes("760.2MiB ") == int(760.2 * 2**20)
    assert parse_bytes("1.5GiB") == int(1.5 * 2**30)
    assert parse_bytes("512kB") == 512_000
    assert parse_bytes("--") is None


def test_workflow_id_is_stable_per_path(tmp_path):
    from wetrun.runner import workflow_id

    a, b = tmp_path / "a.yaml", tmp_path / "b.yaml"
    assert workflow_id(a) == workflow_id(tmp_path / "." / "a.yaml") != workflow_id(b)
    assert len(workflow_id(a)) == 16


def test_oom_detection_waits_for_late_flag_and_falls_back_to_137(monkeypatch):
    """OOMKilled 표시가 늦게 기록돼도(CI에서 실제로 겪음) 메모리 부족을 fail로 오판하지 않는다."""
    import subprocess

    from wetrun import runner

    def fake(inspect_outputs):
        outs = iter(inspect_outputs)

        def run(cmd, **kw):
            out = "c1\n" if cmd[1] == "ps" else next(outs)
            return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")

        return run

    ctx = object.__new__(runner._Run)
    ctx.project = "wetrun-x"
    monkeypatch.setattr(runner.time, "sleep", lambda s: None)
    monkeypatch.setattr(subprocess, "run", fake(["/svc false 137", "/svc true 137"]))
    assert ctx.oom_killed() == ["svc"]  # 다시 보니 표시됨
    monkeypatch.setattr(subprocess, "run", fake(["/svc false 137"] * 10))
    assert ctx.oom_killed() == ["svc"]  # 끝까지 표시 없어도 137이면 메모리 부족
    monkeypatch.setattr(subprocess, "run", fake(["/svc false 1"]))
    assert ctx.oom_killed() == []  # 보통 실패는 메모리 부족이 아님
