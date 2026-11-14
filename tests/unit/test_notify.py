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


def body(status, **kw):
    cleanup = kw.pop("cleanup_errors", ())
    return notify.payload(result(status, cleanup_errors=cleanup), **kw)


def card(b):
    return b["embeds"][0]


def field(b, name):
    return next(f["value"] for f in card(b)["fields"] if f["name"].startswith(name))


def test_fail_card_reads_cause_then_todo():
    b = body(Status.FAIL, title="svc", report_path="/data/runs/r1.json")
    assert b["content"] == "❌ **FAIL · svc** — `photos` 단계"  # 푸시 미리보기에 보이는 줄
    assert b["username"] == "Wetrun" and "flags" not in b  # 실패는 울린다
    c = card(b)
    assert c["color"] == notify.COLOR["fail"] and c["title"] == "백업에 문제가 있어요"
    assert c["description"].index("> 체크섬이 다른 파일 1개") < c["description"].index("**할 일**")
    assert c["timestamp"] == "2026-11-14T09:00:00+09:00"
    assert field(b, "리포트") == "`/data/runs/r1.json`"
    # 리포트 칸이 있으면 실행 ID는 경로에 있으니 맨 아래에서 뺀다
    assert c["footer"]["text"] == f"{notify.socket.gethostname()} · 스냅샷 abcdef12 · 총 70.0초"


def test_steps_box_lines_up():
    box = field(body(Status.FAIL), "단계")
    assert box.startswith("```\n") and box.endswith("\n```")
    rows = box.split("\n")[1:-1]
    assert rows == ["✅ restore    0.0초", "❌ photos     0.0초"]


def test_error_card_says_not_a_backup_problem():
    r = result(Status.ERROR)
    r.steps.append(StepResult("ready", "http", Status.SKIPPED))
    b = notify.payload(r)
    assert card(b)["description"].startswith("백업이 망가졌다는 뜻은 아니에요.")
    assert card(b)["color"] == notify.COLOR["error"]
    assert "⏭️ ready    건너뜀" in field(b, "단계")


def test_pass_is_silent_and_short():
    b = body(Status.PASS, report_path="/data/runs/r1.json")
    assert b["flags"] == notify.SUPPRESS_NOTIFICATIONS  # 채널엔 남고 푸시는 안 울림
    assert b["content"].endswith("— 2단계 모두 통과")
    assert not any(f["name"] == "리포트" for f in card(b)["fields"])
    assert "실행 r1" in card(b)["footer"]["text"]


def test_cleanup_error_rings_and_is_listed():
    errs = [f"network n{i} 남음" for i in range(7)]
    b = body(Status.PASS, cleanup_errors=errs)
    assert "flags" not in b  # 정리 실패는 pass여도 울린다
    assert b["content"].endswith("· 정리 실패")
    listed = field(b, "정리 오류 7개")
    assert "network n4 남음" in listed and "network n5 남음" not in listed
    assert "그 밖에 2개" in listed


def test_missing_snapshot_is_left_out():
    r = result(Status.ERROR)
    r.snapshot_id = ""
    assert "스냅샷" not in card(notify.payload(r))["footer"]["text"]


def test_report_path_under_home_is_shortened():
    path = str(notify.Path.home() / ".local/share/wetrun/runs/r1.json")
    assert (
        field(body(Status.FAIL, report_path=path), "리포트")
        == "`~/.local/share/wetrun/runs/r1.json`"
    )


def test_backtick_in_step_name_keeps_box():
    r = result(Status.FAIL)
    r.steps[0].name = "a```b"
    box = field(notify.payload(r), "단계")
    assert box.count("```") == 2


def test_card_fits_discord_limits():
    r = result(Status.FAIL)
    r.steps[1].message = "x" * 5000
    r.steps += [
        StepResult("s" * 60 + str(i), "http", Status.ERROR, message="y" * 500) for i in range(40)
    ]
    r.cleanup_errors = ["z" * 3000] * 9
    b = notify.payload(r, title="t" * 3000, report_path="/r/" + "p" * 3000)
    c = card(b)
    assert len(b["content"]) <= 2000 and len(c["title"]) <= 256 and len(c["description"]) <= 4096
    assert all(len(f["name"]) <= 256 and len(f["value"]) <= 1024 for f in c["fields"])
    total = len(c["title"]) + len(c["description"]) + len(c["footer"]["text"])
    total += sum(len(f["name"]) + len(f["value"]) for f in c["fields"])
    assert total <= 6000


def test_secrets_are_masked_in_card():
    r = result(Status.FAIL)
    r.steps[1].message = "pw=hunter2"
    b = notify.payload(r, ["hunter2"])
    assert "hunter2" not in json.dumps(b, ensure_ascii=False)


def test_send_posts_message(webhook):
    url, received, _ = webhook
    ok, reason = notify.send(url, result(Status.FAIL), title="svc", allow_http=True)
    assert ok, reason
    assert received[0]["content"].startswith("❌ **FAIL · svc**")
    assert received[0]["username"] == "Wetrun"
    assert received[0]["allowed_mentions"] == {"parse": []}  # @everyone 호출 막기
    assert "secret-token" not in json.dumps(received[0], ensure_ascii=False)


def test_send_never_raises(monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("x")

    monkeypatch.setattr(notify, "payload", broken)
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
