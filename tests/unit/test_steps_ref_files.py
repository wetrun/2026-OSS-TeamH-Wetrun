import base64
import hashlib
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from wetrun.contract import Status
from wetrun.steps import ref_files
from wetrun.steps._common import run
from wetrun.steps.ref_files import sample_size, shuffled, upper_bound

PHOTOS = {"a.png": b"aaa", "b.png": b"bbb", "c.png": b"ccc"}
PASSWORD = "pw-secret"
TOKEN = "tok-secret"


def sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


class FakeService:
    """가짜 서비스. 테스트마다 files·album_count·login_status를 바꿔 고장을 흉내 낸다.

    파일 목록은 쪽(page)마다 2개씩 준다.
    """

    def __init__(self) -> None:
        self.files = dict(PHOTOS)  # 이름 → 실제 내용 (다운로드로 나감)
        self.recorded = {name: sha1(data) for name, data in PHOTOS.items()}  # 서비스 기록
        self.album_count = 2
        self.login_status = 200
        self.downloads: list[str] = []
        self.gone: set[str] = set()  # 기록은 있는데 원본 다운로드가 404인 파일
        self.delay = 0.0  # 다운로드 한 번에 걸리는 시간 (느린 서비스 흉내)

        service = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, status, body=None, raw=None):
                data = raw if raw is not None else json.dumps(body).encode()
                self.send_response(status)
                self.end_headers()
                self.wfile.write(data)

            def authorized(self):
                return self.headers.get("Authorization") == f"Bearer {TOKEN}"

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if self.path == "/login":
                    if service.login_status != 200 or body.get("password") != PASSWORD:
                        return self.reply(
                            service.login_status if service.login_status != 200 else 401, {}
                        )
                    return self.reply(200, {"auth": {"token": TOKEN}})
                if self.path == "/search" and self.authorized():
                    names = sorted(service.files)
                    page = body.get("page", 1)
                    chunk = names[(page - 1) * 2 : page * 2]
                    items = [
                        {
                            "key": name,
                            "fileName": name,
                            "sum": base64.b64encode(bytes.fromhex(service.recorded[name])).decode(),
                        }
                        for name in chunk
                    ]
                    nxt = str(page + 1) if page * 2 < len(names) else None
                    return self.reply(200, {"result": {"items": items, "nextPage": nxt}})
                self.reply(404, {})

            def do_GET(self):
                if not self.authorized():
                    return self.reply(401, {})
                if self.path == "/albums":
                    return self.reply(200, [{"title": "trip", "size": service.album_count}])
                if self.path.startswith("/files/"):
                    name = self.path.split("/")[2]
                    if name in service.gone:
                        return self.reply(404, {})
                    service.downloads.append(name)
                    time.sleep(service.delay)
                    return self.reply(200, raw=service.files[name])
                self.reply(404, {})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.handle_error = lambda request, address: None  # 검사가 먼저 끊은 연결
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, args=(0.05,), daemon=True).start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def service():
    s = FakeService()
    yield s
    s.stop()


@pytest.fixture
def io(tmp_path, monkeypatch):
    """WETRUN_DIR을 임시 폴더로 바꾸고 refs.json을 쓴다."""
    monkeypatch.setenv("WETRUN_DIR", str(tmp_path))
    refs = {
        "assets": [{"filename": n, "sha1": sha1(d)} for n, d in PHOTOS.items()],
        "albums": [{"name": "trip", "asset_count": 2}],
    }
    (tmp_path / "refs.json").write_text(json.dumps(refs))
    return tmp_path


def step(service, **overrides):
    s = {
        "url": service.url,
        "account": {"user": "me", "password": PASSWORD},
        "login": {"path": "/login", "token": "auth.token"},
        "assets": {
            "path": "/search",
            "body": {"size": 2},
            "items": "result.items",
            "id": "key",
            "name": "fileName",
            "checksum": "sum",
            "encoding": "base64",
            "page": "page",
            "next": "result.nextPage",
        },
        "download": "/files/{id}/original",
        "albums": {"path": "/albums", "name": "title", "count": "size"},
        "timeout": 10,
    }
    s.update(overrides)
    return s


# --- 판정 ---


def test_pass_when_everything_matches(service, io):
    status, message, evidence = ref_files.check(step(service))
    assert status is Status.PASS, message
    assert evidence["found"] == 3  # 쪽을 넘겨 끝까지 받음
    assert evidence["download"] == {"checked": 3, "of": 3, "needed": 3}
    assert "전부" in message


def test_login_rejected_is_fail(service, io):
    service.login_status = 401
    status, message, _ = ref_files.check(step(service))
    assert status is Status.FAIL
    assert "로그인" in message


def test_missing_file_is_fail(service, io):
    del service.files["c.png"]
    del service.recorded["c.png"]
    status, message, evidence = ref_files.check(step(service))
    assert status is Status.FAIL
    assert evidence["missing"] == ["c.png"]
    assert message == "빠진 파일 1개: c.png"


def test_recorded_checksum_differs_is_fail(service, io):
    service.recorded["b.png"] = sha1(b"other")
    status, message, evidence = ref_files.check(step(service))
    assert status is Status.FAIL
    assert evidence["checksum_mismatch"] == ["b.png"]
    assert message == "체크섬이 다른 파일 1개: b.png"


def test_downloaded_file_differs_is_fail(service, io):
    service.files["a.png"] = b"broken"  # 기록은 맞는데 실제 파일만 깨짐
    status, message, evidence = ref_files.check(step(service))
    assert status is Status.FAIL
    assert evidence["download"]["mismatch"] == ["a.png"]
    assert message == "다운로드한 원본이 다른 파일 1개: a.png"


def test_original_gone_names_the_file(service, io):
    service.gone.add("b.png")  # 서비스 기록은 있는데 원본 파일만 사라짐
    status, message, _ = ref_files.check(step(service))
    assert status is Status.FAIL
    assert message == "원본 다운로드 실패 (HTTP 404): b.png"


def test_album_shrunk_is_fail(service, io):
    service.album_count = 1
    status, _, evidence = ref_files.check(step(service))
    assert status is Status.FAIL
    assert evidence["albums"] == ["trip: 파일 1개 (기준 2개)"]


def test_extra_files_are_not_fail(service, io):
    service.files["d.png"] = b"ddd"
    service.recorded["d.png"] = sha1(b"ddd")
    status, _, evidence = ref_files.check(step(service))
    assert status is Status.PASS
    assert evidence["found"] == 4


def test_unreachable_service_is_fail(io):
    s = step(SimpleNamespace(url="http://127.0.0.1:9"), timeout=5)
    status, message, _ = ref_files.check(s)
    assert status is Status.FAIL
    assert "응답 없음" in message


@pytest.mark.parametrize(
    "change",
    [
        {"account": None},
        {"login": {"path": "/login"}},
        {"download": "/files/original"},
        {"max_defect_rate": 2},
    ],
)
def test_bad_config_is_error(service, io, change):
    assert ref_files.check(step(service, **change))[0] is Status.ERROR


def test_wrong_field_name_is_error(service, io):
    s = step(service)
    s["assets"] = {**s["assets"], "items": "result.nothing"}
    status, message, _ = ref_files.check(s)
    assert status is Status.ERROR
    assert "assets.items" in message


def test_no_time_left_is_error(service, io):
    assert ref_files.check(step(service, timeout=0))[0] is Status.ERROR


def test_secrets_never_in_result(service, io):
    (io / "step.json").write_text(json.dumps(step(service, url=service.url + "/")))
    service.login_status = 403
    run(ref_files.check)
    result = (io / "out" / "result.json").read_text()
    assert PASSWORD not in result
    assert TOKEN not in result


# --- 다운로드: 시간 안에서 최대한 (3의 법칙) ---


def add_files(service, io, n):
    """서비스와 refs.json에 파일 n개를 더한다."""
    refs = json.loads((io / "refs.json").read_text())
    for i in range(n):
        name, data = f"x{i:03}.png", f"data-{i}".encode()
        service.files[name] = data
        service.recorded[name] = sha1(data)
        refs["assets"].append({"filename": name, "sha1": sha1(data)})
    (io / "refs.json").write_text(json.dumps(refs))


def test_sample_size_rule_of_three():
    assert sample_size(0.01) == 299
    assert sample_size(0.03) == 99
    assert upper_bound(299) < 0.01


def test_same_seed_same_order():
    items = list(range(100))
    assert shuffled(items, 42) == shuffled(items, 42)
    assert sorted(shuffled(items, 42)) == items


def test_enough_files_in_time_is_pass(service, io):
    add_files(service, io, 20)
    service.delay = 0.15
    # 0.8이면 2개만 봐도 됨. 1초 동안 23개를 다 볼 수는 없다
    s = step(service, max_defect_rate=0.8, seed=7, timeout=1)
    status, message, evidence = ref_files.check(s)
    download = evidence["download"]
    assert status is Status.PASS, message
    assert 2 <= download["checked"] < download["of"] == 23
    assert download["seed"] == 7 and "시드 7" in message
    assert "bound" in download


def test_too_few_files_in_time_is_error(service, io):
    add_files(service, io, 20)
    service.delay = 0.15
    status, message, evidence = ref_files.check(step(service, timeout=1))  # 1%면 23개 전부 필요
    assert status is Status.ERROR
    assert "timeout을 늘리거나" in message
    assert evidence["download"]["checked"] < 23


def test_mismatch_found_before_time_runs_out_is_fail(service, io):
    add_files(service, io, 20)
    for name in service.files:
        service.files[name] = b"broken"
    service.delay = 0.15
    status, _, evidence = ref_files.check(step(service, timeout=1))
    assert status is Status.FAIL
    assert evidence["download"]["mismatch"]


def test_message_names_at_most_three_files():
    assert ref_files._names([]) == ""
    assert ref_files._names(["a.png"]) == ": a.png"
    assert ref_files._names([f"{i}.png" for i in range(5)]) == ": 0.png, 1.png, 2.png 외 2개"


def test_mismatch_count_is_not_capped(service, io, monkeypatch):
    monkeypatch.setattr(ref_files, "MAX_LISTED", 1)  # evidence 목록은 잘려도 개수는 전부 센다
    service.files["a.png"] = b"broken"
    service.files["b.png"] = b"broken"
    _, message, evidence = ref_files.check(step(service))
    assert evidence["download"]["mismatch"] in (["a.png"], ["b.png"])  # 순서는 무작위
    assert message.startswith("다운로드한 원본이 다른 파일 2개: ")
