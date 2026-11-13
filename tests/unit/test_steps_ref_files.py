import base64
import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from wetrun.contract import Status
from wetrun.steps import ref_files
from wetrun.steps._common import run
from wetrun.steps.ref_files import choose, sample_size, upper_bound

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
                    service.downloads.append(name)
                    return self.reply(200, raw=service.files[name])
                self.reply(404, {})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
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
    assert evidence["download"] == {"mode": "full", "checked": 3, "of": 3}
    assert "전부" in message


def test_login_rejected_is_fail(service, io):
    service.login_status = 401
    status, message, _ = ref_files.check(step(service))
    assert status is Status.FAIL
    assert "로그인" in message


def test_missing_file_is_fail(service, io):
    del service.files["c.png"]
    del service.recorded["c.png"]
    status, _, evidence = ref_files.check(step(service))
    assert status is Status.FAIL
    assert evidence["missing"] == ["c.png"]


def test_recorded_checksum_differs_is_fail(service, io):
    service.recorded["b.png"] = sha1(b"other")
    status, _, evidence = ref_files.check(step(service))
    assert status is Status.FAIL
    assert evidence["checksum_mismatch"] == ["b.png"]


def test_downloaded_file_differs_is_fail(service, io):
    service.files["a.png"] = b"broken"  # 기록은 맞는데 실제 파일만 깨짐
    status, _, evidence = ref_files.check(step(service))
    assert status is Status.FAIL
    assert evidence["download"]["mismatch"] == ["a.png"]


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


# --- 샘플링 (3의 법칙) ---


def test_sample_size_rule_of_three():
    assert sample_size(0.01) == 299
    assert sample_size(0.03) == 99
    assert upper_bound(299) < 0.01


def test_small_library_is_checked_in_full():
    items = list(range(5))
    assert choose(items, full_scan_below=300, n_sample=299, seed=1) == (items, "full")


def test_large_library_is_sampled_with_seed():
    items = list(range(1000))
    first, mode = choose(items, full_scan_below=300, n_sample=299, seed=42)
    again, _ = choose(items, full_scan_below=300, n_sample=299, seed=42)
    assert mode == "sample"
    assert len(first) == 299
    assert first == again  # 같은 시드면 같은 샘플


def test_sampling_downloads_only_sample(service, io):
    s = step(service, full_scan_below=2, max_defect_rate=0.8, seed=7)
    status, message, evidence = ref_files.check(s)
    assert status is Status.PASS
    assert evidence["download"]["mode"] == "sample"
    assert evidence["download"]["checked"] == len(service.downloads) == sample_size(0.8)
    assert "시드 7" in message
