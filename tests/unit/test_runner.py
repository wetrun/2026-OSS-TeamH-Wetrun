import json

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
