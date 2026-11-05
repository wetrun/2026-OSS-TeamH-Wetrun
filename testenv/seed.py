"""testenv Immich에 정해진 데이터를 넣고 refs.json(정답지)을 만든다.

하는 일: 샘플 사진 생성 → 관리자 생성 → 로그인 → 사진 업로드 → 앨범 생성 → refs.json 작성.
여러 번 실행해도 같은 결과가 나온다 (이미 있는 관리자·사진·앨범은 그대로 쓴다).

실행: make seed  (또는 uv run python testenv/seed.py)
표준 라이브러리만 쓴다.
"""

import hashlib
import json
import struct
import sys
import time
import urllib.error
import urllib.request
import uuid
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
SAMPLES = HERE / "samples"
REFS = HERE / "refs.json"

# 샘플 사진: (파일 이름, 왼쪽 위 색, 오른쪽 아래 색, 촬영 시각). 바꾸면 refs.json도 바뀐다.
SAMPLE_SPECS = [
    ("sample-01-red.png", (220, 40, 40), (250, 200, 60), "2026-01-01T09:00:00.000Z"),
    ("sample-02-green.png", (30, 160, 70), (200, 240, 120), "2026-01-02T10:00:00.000Z"),
    ("sample-03-blue.png", (30, 80, 200), (120, 220, 250), "2026-01-03T11:00:00.000Z"),
    (
        "sample-04-purple.png",
        (120, 40, 160),
        (240, 150, 220),
        "2026-01-04T12:00:00.000Z",
    ),
    ("sample-05-gray.png", (40, 40, 40), (230, 230, 230), "2026-01-05T13:00:00.000Z"),
]
# 앨범에 넣을 사진 (앞의 3장). 나머지는 앨범 밖에 둔다.
ALBUM_SAMPLE_COUNT = 3
WIDTH, HEIGHT = 320, 240


def load_env() -> dict[str, str]:
    """.env.example을 기본값으로, .env가 있으면 그 값으로 덮어쓴다.

    줄 끝 \\r(Windows 줄바꿈)과 값 양쪽의 따옴표는 지운다.
    """
    env: dict[str, str] = {}
    for name in (".env.example", ".env"):
        path = HERE / name
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip()
            # 셸처럼 값 양쪽의 따옴표를 벗긴다 (KEY="value" == KEY=value)
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            env[key.strip()] = value
    return env


def make_png(top_left: tuple[int, int, int], bottom_right: tuple[int, int, int]) -> bytes:
    """대각선 그라데이션 PNG를 만든다.

    압축 수준 0(무압축)을 써서 zlib 버전과 상관없이 누가 만들어도 바이트가 똑같다.
    """
    rows = []
    for y in range(HEIGHT):
        row = bytearray([0])  # 각 줄 앞의 필터 바이트 (0 = 없음)
        for x in range(WIDTH):
            t = (x / (WIDTH - 1) + y / (HEIGHT - 1)) / 2
            row += bytes(
                round(a + (b - a) * t) for a, b in zip(top_left, bottom_right, strict=True)
            )
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(kind: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

    header = struct.pack(">IIBBBBB", WIDTH, HEIGHT, 8, 2, 0, 0, 0)  # 8비트 RGB
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 0))
        + chunk(b"IEND", b"")
    )


def ensure_samples() -> list[Path]:
    SAMPLES.mkdir(exist_ok=True)
    paths = []
    for filename, top_left, bottom_right, _ in SAMPLE_SPECS:
        path = SAMPLES / filename
        data = make_png(top_left, bottom_right)
        if not path.exists() or path.read_bytes() != data:
            path.write_bytes(data)
        paths.append(path)
    print(f"prepared {len(paths)} sample photos: {SAMPLES.relative_to(HERE.parent)}/")
    return paths


class Immich:
    """Immich API를 부르는 작은 클라이언트."""

    def __init__(self, base_url: str) -> None:
        self.base = base_url.rstrip("/") + "/api"
        self.token: str | None = None

    def request(
        self,
        method: str,
        path: str,
        body: dict | list | None = None,
        *,
        data: bytes | None = None,
        content_type: str | None = None,
    ) -> tuple[int, object]:
        headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode()
            content_type = "application/json"
        if content_type:
            headers["Content-Type"] = content_type
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                status, raw = resp.status, resp.read()
        except urllib.error.HTTPError as err:
            status, raw = err.code, err.read()
        try:
            return status, json.loads(raw) if raw else None
        except json.JSONDecodeError:
            return status, raw.decode(errors="replace")

    def wait_ready(self, timeout: int = 180) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                status, body = self.request("GET", "/server/ping")
                if status == 200 and isinstance(body, dict) and body.get("res") == "pong":
                    return
            except OSError:
                pass
            time.sleep(3)
        sys.exit(f"error: Immich did not respond within {timeout}s. Did you run make env-up?")

    def upload(self, path: Path, taken_at: str) -> tuple[str, str]:
        """사진 1장을 올리고 (asset id, created|duplicate)를 돌려준다."""
        boundary = uuid.uuid4().hex
        fields = {
            "fileCreatedAt": taken_at,
            "fileModifiedAt": taken_at,
            "filename": path.name,
        }
        parts = []
        for name, value in fields.items():
            parts.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'
                f"{value}\r\n".encode()
            )
        parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="assetData"; filename="{path.name}"\r\n'
            "Content-Type: image/png\r\n\r\n".encode()
            + path.read_bytes()
            + b"\r\n"
        )
        parts.append(f"--{boundary}--\r\n".encode())
        status, body = self.request(
            "POST",
            "/assets",
            data=b"".join(parts),
            content_type=f"multipart/form-data; boundary={boundary}",
        )
        if status not in (200, 201) or not isinstance(body, dict):
            sys.exit(f"error: failed to upload {path.name} (HTTP {status}): {body}")
        return body["id"], body["status"]


def main() -> None:
    env = load_env()
    url = env.get("IMMICH_URL", "http://localhost:2283")
    email = env["TESTENV_ADMIN_EMAIL"]
    password = env["TESTENV_ADMIN_PASSWORD"]
    name = env["TESTENV_ADMIN_NAME"]
    album_name = env["TESTENV_ALBUM_NAME"]

    samples = ensure_samples()
    api = Immich(url)
    api.wait_ready()

    # 1. 관리자 생성 (이미 있으면 건너뜀)
    status, body = api.request(
        "POST",
        "/auth/admin-sign-up",
        {"email": email, "password": password, "name": name},
    )
    if status in (200, 201):
        print(f"created admin: {email}")
    elif status == 400 and "admin" in str(body).lower():
        print(f"admin already exists: logging in as {email}")
    else:
        sys.exit(f"error: failed to create admin (HTTP {status}): {body}")

    # 2. 로그인
    status, body = api.request("POST", "/auth/login", {"email": email, "password": password})
    if status not in (200, 201) or not isinstance(body, dict):
        sys.exit(f"error: login failed (HTTP {status}). Check TESTENV_ADMIN_* in .env")
    api.token = body["accessToken"]

    # 3. 첫 접속 설정 화면 건너뛰기 (웹에서 바로 타임라인이 보이게)
    api.request("POST", "/system-metadata/admin-onboarding", {"isOnboarded": True})
    api.request("PUT", "/users/me/onboarding", {"isOnboarded": True})

    # 4. 사진 업로드 (같은 사진은 Immich가 duplicate로 알려 주고 기존 id를 돌려준다)
    assets = []
    for path, (_, _, _, taken_at) in zip(samples, SAMPLE_SPECS, strict=True):
        asset_id, result = api.upload(path, taken_at)
        data = path.read_bytes()
        assets.append(
            {
                "id": asset_id,
                "filename": path.name,
                "sha1": hashlib.sha1(data).hexdigest(),
                "size": len(data),
                "taken_at": taken_at,
            }
        )
        print(f"uploaded {path.name}: {result}")

    # 5. 앨범 생성 (같은 이름이 있으면 그 앨범에 사진만 추가)
    album_assets = assets[:ALBUM_SAMPLE_COUNT]
    album_ids = [a["id"] for a in album_assets]
    status, albums = api.request("GET", "/albums")
    existing = (
        next((a for a in albums if a.get("albumName") == album_name), None)
        if status == 200 and isinstance(albums, list)
        else None
    )
    if existing:
        api.request("PUT", f"/albums/{existing['id']}/assets", {"ids": album_ids})
        album_id = existing["id"]
        print(f"album already exists: {album_name}")
    else:
        status, body = api.request(
            "POST", "/albums", {"albumName": album_name, "assetIds": album_ids}
        )
        if status not in (200, 201) or not isinstance(body, dict):
            sys.exit(f"error: failed to create album (HTTP {status}): {body}")
        album_id = body["id"]
        print(f"created album: {album_name} ({len(album_ids)} photos)")

    # 6. refs.json: 복구 결과와 비교할 정답지. 비밀번호는 넣지 않는다.
    refs = {
        "immich_version": env.get("IMMICH_VERSION"),
        "user": {"email": email, "name": name},
        "asset_count": len(assets),
        "assets": assets,
        "albums": [
            {
                "id": album_id,
                "name": album_name,
                "asset_count": len(album_assets),
                "filenames": [a["filename"] for a in album_assets],
            }
        ],
    }
    REFS.write_text(json.dumps(refs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote reference file: {REFS.relative_to(HERE.parent)}")
    print(f"done: log in at {url} as {email}")


if __name__ == "__main__":
    main()
