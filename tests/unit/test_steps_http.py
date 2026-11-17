import json
import time

from wetrun.contract import Status
from wetrun.steps import http
from wetrun.steps._common import deadline, run


def fake_probe(*responses):
    """probe 대신 정해진 응답을 차례로 돌려준다 (마지막 응답은 계속 반복)."""
    queue = list(responses)

    def probe(url, timeout, headers=None):
        return queue.pop(0) if len(queue) > 1 else queue[0]

    return probe


# --- http 판정 ---


def test_pass_when_expected_status_arrives(monkeypatch):
    monkeypatch.setattr(http, "probe", fake_probe(503, 200))
    status, _, evidence = http.check({"url": "http://app:80/", "interval": 0.01, "timeout": 5})
    assert status is Status.PASS
    assert evidence["attempts"] == 2


def test_fail_when_other_status_until_deadline(monkeypatch):
    monkeypatch.setattr(http, "probe", fake_probe(500))
    status, _, evidence = http.check({"url": "http://app:80/", "interval": 0.05, "timeout": 0.2})
    assert status is Status.FAIL
    assert evidence["last"] == 500


def test_fail_when_connection_refused_until_deadline():
    step = {"url": "http://127.0.0.1:9/", "interval": 0.05, "timeout": 0.3}
    status, _, evidence = http.check(step)
    assert status is Status.FAIL
    assert evidence["last"] == "ConnectionRefusedError"


def test_expect_status_can_be_401(monkeypatch):
    monkeypatch.setattr(http, "probe", fake_probe(401))
    step = {"url": "http://app:80/", "expect_status": 401, "timeout": 5}
    assert http.check(step)[0] is Status.PASS


def test_missing_url_is_error():
    assert http.check({"timeout": 5})[0] is Status.ERROR


def test_interval_zero_is_error():
    step = {"url": "http://127.0.0.1:9/", "interval": 0, "timeout": 1}
    assert http.check(step)[0] is Status.ERROR


def test_no_request_sent_is_error(monkeypatch):
    monkeypatch.setattr(http, "probe", fake_probe(200))
    assert http.check({"url": "http://app:80/", "timeout": 0})[0] is Status.ERROR


def test_safe_url_hides_credentials_and_query():
    url = "http://user:secret@app:2283/api/ping?token=abc"
    assert http.safe_url(url) == "http://app:2283/api/ping"


# --- 공통 입출력 ---


def test_deadline_uses_full_timeout():
    before = time.monotonic()
    end = deadline({"timeout": 120})
    assert before + 120 <= end <= time.monotonic() + 120


def read_result(tmp_path):
    return json.loads((tmp_path / "out" / "result.json").read_text(encoding="utf-8"))


def test_run_writes_result_and_exit_code(tmp_path, monkeypatch):
    monkeypatch.setenv("WETRUN_DIR", str(tmp_path))
    (tmp_path / "step.json").write_text("{}")

    code = run(lambda step: (Status.FAIL, "응답 없음", {"last": 500}))

    assert code == 1
    assert read_result(tmp_path)["status"] == "fail"


def test_exception_ends_as_error_without_message(tmp_path, monkeypatch):
    monkeypatch.setenv("WETRUN_DIR", str(tmp_path))
    (tmp_path / "step.json").write_text("{}")

    def broken(step):
        raise ValueError("password=secret")

    code = run(broken)

    assert code == 2
    result = read_result(tmp_path)
    assert result["status"] == "error"
    assert "secret" not in json.dumps(result)


def test_unwritable_evidence_ends_as_error(tmp_path, monkeypatch):
    monkeypatch.setenv("WETRUN_DIR", str(tmp_path))
    (tmp_path / "step.json").write_text("{}")

    code = run(lambda step: (Status.PASS, "ok", {"raw": b"bytes"}))

    assert code == 2
    assert read_result(tmp_path)["status"] == "error"


def test_missing_step_json_is_error(tmp_path, monkeypatch):
    monkeypatch.setenv("WETRUN_DIR", str(tmp_path))
    assert run(lambda step: (Status.PASS, "ok", {})) == 2


def test_headers_are_sent(monkeypatch):
    """접속 주소를 검사하는 서비스(Nextcloud 등)는 Host 헤더가 맞아야 응답한다."""
    import http.server as httpserver  # 검사 모듈 이름(http)을 가리지 않게
    import threading

    seen = {}

    class Handler(httpserver.BaseHTTPRequestHandler):
        def do_GET(self):
            seen["host"] = self.headers.get("Host")
            self.send_response(200 if seen["host"] == "localhost" else 400)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = httpserver.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/status"
    try:
        assert http.check({"url": url, "timeout": 3, "interval": 0.2})[0] == Status.FAIL
        status, _, evidence = http.check(
            {"url": url, "timeout": 3, "headers": {"Host": "localhost"}}
        )
        assert status == Status.PASS and seen["host"] == "localhost"
        assert "headers" not in evidence  # 헤더 값(토큰 등)은 남기지 않는다
        assert http.check({"url": url, "headers": {"Host": 1}})[0] == Status.ERROR
    finally:
        server.shutdown()
