import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from wetrun import notify
from wetrun.contract import RunResult, Status, StepResult


def result(status, cleanup_errors=()):
    return RunResult(
        run_id="r1",
        snapshot_id="abcdef12",
        workflow_sha256="0" * 64,
        started_at="2026-11-14T09:00:00+09:00",
        duration_s=70.0,
        steps=[
            StepResult("restore", "restore", Status.PASS),
            StepResult("photos", "ref_files", status, message="체크섬이 다른 파일 1개"),
        ],
        cleanup_errors=list(cleanup_errors),
    )


@pytest.fixture
def webhook():
    """받은 본문을 기록하는 가짜 웹훅. status를 바꿔 실패를 흉내 낸다."""
    received = []
    state = {"status": 204}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(state["status"])
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, args=(0.05,), daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/api/webhooks/1/secret-token"
    yield url, received, state
    server.shutdown()
    server.server_close()


def test_notify_on_fail_and_error_only():
    assert notify.should_notify(result(Status.FAIL))
    assert notify.should_notify(result(Status.ERROR))
    assert not notify.should_notify(result(Status.PASS))
    assert notify.should_notify(result(Status.PASS), when=["pass"])


def test_when_can_be_one_word():
    # YAML `when: fail`은 목록이 아니라 글자 하나로 읽힌다
    assert notify.should_notify(result(Status.FAIL), when="fail")
    assert not notify.should_notify(result(Status.ERROR), when="fail")


def test_cleanup_error_always_notifies():
    assert notify.should_notify(result(Status.PASS, cleanup_errors=["남음"]), when=[])


def test_message_has_next_action_and_cleanup_list():
    text = notify.message(
        result(Status.FAIL, cleanup_errors=[f"network n{i} 남음" for i in range(7)])
    )
    assert "할 일: 남은 자원을 직접 지워야 함" in text
    assert "할 일: 백업이나 복구한 데이터에 문제가 있음. photos 단계를 확인" in text
    assert "network n4 남음" in text and "network n5 남음" not in text
    assert "그 밖에 2개" in text


def test_message_lists_problem_steps():
    text = notify.message(result(Status.FAIL))
    assert "FAIL" in text
    assert "photos" in text and "체크섬" in text
    assert "restore" not in text  # 통과한 단계는 빼고 짧게


def test_message_fits_discord_limit():
    r = result(Status.FAIL)
    r.steps += [StepResult(f"s{i}", "http", Status.ERROR, message="x" * 190) for i in range(30)]
    text = notify.message(r, report_path="runs/r1.json")
    assert len(text) <= notify.DISCORD_LIMIT
    assert text.startswith("⚠️ **Wetrun ERROR")  # 첫 줄 판정은 남는다 (error가 섞이면 error)
    assert text.endswith("리포트: `runs/r1.json`")  # 어디서 볼지도 남는다
    assert "나머지는 리포트에" in text


def test_title_first_and_record_last():
    text = notify.message(result(Status.FAIL), title="immich", report_path="/data/runs/r1.json")
    lines = text.splitlines()
    assert lines[0].startswith("❌ **Wetrun FAIL · immich**")  # 푸시 미리보기에 보이는 줄
    assert lines[1].startswith("할 일:")
    assert notify.socket.gethostname() in lines[-2] and "`r1`" in lines[-2]
    assert lines[-1] == "리포트: `/data/runs/r1.json`"


def test_send_posts_message(webhook):
    url, received, _ = webhook
    ok, reason = notify.send(url, result(Status.FAIL), title="svc", allow_http=True)
    assert ok, reason
    assert received[0]["content"].startswith("❌ **Wetrun FAIL · svc**")
    assert "photos" in received[0]["content"]
    assert received[0]["allowed_mentions"] == {"parse": []}  # @everyone 호출 막기
    assert "secret-token" not in received[0]["content"]


def test_send_never_raises(monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("x")

    monkeypatch.setattr(notify, "message", broken)
    ok, reason = notify.send("https://example.test/hook", result(Status.FAIL))
    assert not ok and "알림을 만들지 못함" in reason


def test_send_skips_pass(webhook):
    url, received, _ = webhook
    assert notify.send(url, result(Status.PASS), allow_http=True)[0] is False
    assert received == []


def test_failure_never_leaks_webhook(webhook):
    url, _, state = webhook
    state["status"] = 404
    ok, reason = notify.send(url, result(Status.FAIL), allow_http=True)
    assert not ok and "404" in reason
    assert "secret-token" not in reason


def test_unreachable_webhook_is_reported():
    ok, reason = notify.send("http://127.0.0.1:9/hook", result(Status.FAIL), allow_http=True)
    assert not ok and "전송 실패" in reason


def test_http_webhook_refused():
    ok, reason = notify.send("http://example.test/hook", result(Status.FAIL))
    assert not ok and "https" in reason
