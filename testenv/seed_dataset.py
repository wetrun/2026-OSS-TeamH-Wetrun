"""대용량 평가용: testenv Immich에 데이터셋 N개(JPEG 사진 + MP4 동영상)를 넣고 refs.json에 기록한다.

seed와 나뉘어 있다. 먼저 make env-up, make seed(관리자·샘플 5장·앨범·refs.json)를 한 뒤에 실행한다.
하는 일: 데이터셋 생성 → 업로드 → Immich 작업 대기열이 빌 때까지 대기
→ refs.json에 데이터셋 항목 추가 (샘플은 그대로 두고, 전에 넣은 데이터셋 항목은 새로 바꾼다).

데이터셋은 휴대폰 사진·동영상을 흉내 낸다.
- 사진: 4032x3024(1200만 화소) JPEG, 장당 약 2.7 / 3.7 / 5.2MB (품질 3단계를 번호로 정한다).
- 동영상: --video-every번째마다 1개(기본 50개 중 1개). 1920x1080 30fps H.264 MP4,
  16Mbps(휴대폰 1080p 수준)로 5~15초 → 약 10~30MB.
- 내용은 ffmpeg 테스트 화면(testsrc2) + 잡음이다.
  실제 사진처럼 이미 압축돼 있어 restic으로 줄지 않는다.
- JPEG·MP4는 Immich 서버 이미지 안의 ffmpeg로 만든다 (docker run, 새로 설치할 것 없음).
  Immich 버전(IMMICH_VERSION)이 같으면 ffmpeg도 같아서, 누가 만들어도 같은 바이트가 나온다.
  모든 파일의 내용은 서로 다르다
  (같은 파일은 Immich가 duplicate로 거부하고 restic도 한 번만 저장한다).
- 여러 번 실행해도 된다. 이미 만든 파일은 다시 만들지 않고, 이미 올린 파일은 duplicate로 건너뛴다.
  --count는 데이터셋 전체 개수다: 295 다음에 1495를 주면 1200개만 새로 올라간다.
- 295개 약 1.2GB, 1495개 약 6GB, 2995개 약 12GB.
  디스크는 원본·library·restic·복구본으로 약 4배 필요.

실행: make seed → make seed-dataset N=295  (또는 uv run python testenv/seed_dataset.py --count 295)
Python은 표준 라이브러리만 쓴다.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import seed

HERE = Path(__file__).resolve().parent
# 생성 방식이 바뀌면 폴더 이름도 바꾼다 (예전 파일과 섞이지 않게)
DATASET = HERE / "dataset" / "v3"
# 촬영 시각: 기준 시각 + 번호 x 1분. 샘플 5장(2026-01)과 겹치지 않게 2025년부터 시작한다.
BASE_TIME = datetime(2025, 1, 1, tzinfo=UTC)
PHOTO_SIZE = "4032x3024"
# JPEG 품질(-q:v, 작을수록 좋음) → 4032x3024에서 약 5.2 / 3.7 / 2.7MB
PHOTO_QUALITIES = (2, 3, 4)
VIDEO_SIZE, VIDEO_FPS, VIDEO_BITRATE = "1920x1080", 30, "16M"
VIDEO_SECONDS = (5, 15)
NOISE = "noise=alls=24:allf=t+u"
# 같은 입력 → 같은 바이트: 인코더 정보·메타데이터를 넣지 않는다
BITEXACT = ["-map_metadata", "-1", "-fflags", "+bitexact", "-flags", "+bitexact"]
MIME = {".jpg": "image/jpeg", ".mp4": "video/mp4"}


def fraction(idx: int, what: str) -> float:
    """번호로 정해지는 0 이상 1 미만의 수"""
    digest = hashlib.sha256(f"wetrun-dataset-{what}-{idx}".encode()).digest()
    return int.from_bytes(digest[:4], "big") / 2**32


def is_video(idx: int, video_every: int) -> bool:
    return video_every > 0 and idx % video_every == video_every - 1


def photo_quality(idx: int) -> int:
    return PHOTO_QUALITIES[int(fraction(idx, "photo-quality") * len(PHOTO_QUALITIES))]


def video_seconds(idx: int) -> int:
    lo, hi = VIDEO_SECONDS
    return lo + int(fraction(idx, "video-seconds") * (hi - lo + 1))


class Ffmpeg:
    """Immich 서버 이미지 안의 ffmpeg를 돌린다. 출력은 DATASET 폴더(컨테이너 안 /out)에 쓴다.

    TESTENV_FFMPEG=local이면 이 컴퓨터의 ffmpeg를 쓴다 (버전이 달라 바이트가 다를 수 있다. 시험용).
    """

    def __init__(self, image: str) -> None:
        self.local = os.environ.get("TESTENV_FFMPEG") == "local"
        self.image = image
        if self.local:
            if not shutil.which("ffmpeg"):
                sys.exit("error: TESTENV_FFMPEG=local but ffmpeg is not installed")
            return
        if not shutil.which("docker"):
            sys.exit("error: docker not found")
        found = subprocess.run(
            ["docker", "image", "inspect", image], capture_output=True, check=False
        )
        if found.returncode != 0:
            sys.exit(f"error: Docker image {image} not found. Run make env-up first")

    def run(self, args: list[str]) -> None:
        """args 안의 '/out'은 DATASET 폴더를 가리킨다."""
        if self.local:
            cmd = ["ffmpeg", *[str(DATASET) + a[4:] if a.startswith("/out/") else a for a in args]]
        else:
            cmd = [
                "docker", "run", "--rm",
                "--user", f"{os.getuid()}:{os.getgid()}",
                "-v", f"{DATASET}:/out",
                "--entrypoint", "sh",
                self.image,
                "-c", 'exec ffmpeg "$@"', "ffmpeg",
                *args,
            ]  # fmt: skip
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            sys.exit(f"error: ffmpeg failed: {result.stderr.strip()[-500:]}")


def make_photos(ff: Ffmpeg, indices: list[int], missing: set[int]) -> None:
    """사진은 품질별로 한 번의 ffmpeg 실행에서 프레임 하나당 JPEG 하나로 만든다 (빠르다).

    품질 그룹의 j번째 사진 = 그 그룹 j번째 프레임. 번호가 늘어도 앞 프레임은 그대로라 같은 바이트다.
    """
    for q in PHOTO_QUALITIES:
        group = [i for i in indices if photo_quality(i) == q]
        if not any(i in missing for i in group):
            continue
        tmp = DATASET / f".tmp-q{q}"
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir()
        ff.run([
            "-v", "error",
            "-f", "lavfi", "-i", f"testsrc2=s={PHOTO_SIZE}:r=1,{NOISE}:all_seed={q}",
            "-frames:v", str(len(group)), "-q:v", str(q), *BITEXACT,
            "-start_number", "0", "-f", "image2", f"/out/{tmp.name}/f_%06d.jpg",
        ])  # fmt: skip
        for j, idx in enumerate(group):
            if idx in missing:
                os.replace(tmp / f"f_{j:06d}.jpg", DATASET / f"dataset-{idx:06d}.jpg")
        shutil.rmtree(tmp)


def make_video(ff: Ffmpeg, idx: int) -> None:
    """동영상 1개. x264는 스레드 하나로 돌려야 매번 같은 바이트가 나온다 (비트레이트 제어 때문)."""
    name = f"dataset-{idx:06d}.mp4"
    ff.run([
        "-v", "error", "-y",
        "-f", "lavfi", "-i",
        f"testsrc2=s={VIDEO_SIZE}:r={VIDEO_FPS},{NOISE}:all_seed={idx}",
        "-t", str(video_seconds(idx)),
        "-c:v", "libx264", "-preset", "ultrafast", "-threads", "1",
        "-b:v", VIDEO_BITRATE, "-maxrate", VIDEO_BITRATE, "-bufsize", VIDEO_BITRATE,
        "-pix_fmt", "yuv420p", *BITEXACT, "-movflags", "+faststart",
        f"/out/{name}.tmp.mp4",
    ])  # fmt: skip
    os.replace(DATASET / f"{name}.tmp.mp4", DATASET / name)


def taken_at(idx: int) -> str:
    return (BASE_TIME + timedelta(minutes=idx)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def ensure_dataset(count: int, video_every: int, image: str) -> list[Path]:
    """dataset/v3/에 count개를 준비한다. 이미 있는 파일은 다시 만들지 않는다."""
    DATASET.mkdir(parents=True, exist_ok=True)
    paths = [
        DATASET / f"dataset-{i:06d}.{'mp4' if is_video(i, video_every) else 'jpg'}"
        for i in range(count)
    ]
    videos = [i for i in range(count) if is_video(i, video_every)]
    photos = [i for i in range(count) if not is_video(i, video_every)]
    missing = {i for i, p in enumerate(paths) if not p.exists()}
    print(
        f"preparing {count} dataset files ({len(photos)} JPEG photos, {len(videos)} MP4 videos): "
        f"{DATASET.relative_to(HERE.parent)}/ ({len(missing)} to generate)"
    )
    if missing:
        ff = Ffmpeg(image)
        start = time.monotonic()
        make_photos(ff, photos, missing)
        todo = [i for i in videos if i in missing]
        for n, idx in enumerate(todo, 1):
            make_video(ff, idx)
            print(f"  made video {n}/{len(todo)}", flush=True)
        print(f"generated {len(missing)} files in {time.monotonic() - start:.0f}s")
    total = sum(p.stat().st_size for p in paths)
    print(f"dataset ready: {total / 1024**3:.2f} GiB")
    return paths


def upload_all(api: seed.Immich, paths: list[Path], workers: int) -> list[dict]:
    """파일을 올리고 refs.json에 넣을 항목을 돌려준다 (번호 순서)."""

    def one(item: tuple[int, Path]) -> tuple[dict, str]:
        idx, path = item
        asset_id, result = api.upload(path, taken_at(idx), MIME[path.suffix])
        data = path.read_bytes()
        ref = {
            "id": asset_id,
            "filename": path.name,
            "sha1": hashlib.sha1(data).hexdigest(),
            "size": len(data),
            "taken_at": taken_at(idx),
        }
        return ref, result

    refs: list[dict] = []
    counts = {"created": 0, "duplicate": 0}
    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for n, (ref, result) in enumerate(pool.map(one, enumerate(paths)), 1):
            refs.append(ref)
            counts[result] = counts.get(result, 0) + 1
            if n % 100 == 0 or n == len(paths):
                print(
                    f"  uploaded {n}/{len(paths)} (created {counts['created']}, "
                    f"duplicate {counts['duplicate']})",
                    flush=True,
                )
    print(f"upload took {time.monotonic() - start:.0f}s")
    return refs


def pending_jobs(body: object) -> int:
    """GET /api/queues 응답에서 남은 작업(active + waiting + delayed) 수를 센다.

    응답 모양이 버전마다 조금씩 달라서, 어디에 있든 해당 이름의 숫자를 모두 더한다.
    """
    if isinstance(body, dict):
        total = 0
        for key, value in body.items():
            if key in ("active", "waiting", "delayed") and isinstance(value, int):
                total += value
            else:
                total += pending_jobs(value)
        return total
    if isinstance(body, list):
        return sum(pending_jobs(v) for v in body)
    return 0


def wait_queues(api: seed.Immich, timeout: int) -> None:
    """썸네일·메타데이터 작업이 끝나야 DB가 안정된다. 그 전에 백업하면 측정마다 상태가 다르다."""
    start = time.monotonic()
    zero_streak = 0
    last_print = 0.0
    while time.monotonic() - start < timeout:
        status, body = api.request("GET", "/queues")
        if status != 200:
            print(f"warning: GET /api/queues returned HTTP {status}; skipping queue wait")
            return
        left = pending_jobs(body)
        # 작업이 잠깐 0이 됐다가 다음 단계 작업이 생기기도 해서, 세 번 연속 0일 때 끝으로 본다
        zero_streak = zero_streak + 1 if left == 0 else 0
        if zero_streak >= 3:
            print(f"job queues empty after {time.monotonic() - start:.0f}s")
            return
        if time.monotonic() - last_print >= 30:
            print(
                f"  waiting for Immich jobs: {left} left ({time.monotonic() - start:.0f}s)",
                flush=True,
            )
            last_print = time.monotonic()
        time.sleep(5)
    sys.exit(f"error: Immich jobs did not finish within {timeout}s (use --queue-timeout)")


def main() -> None:
    p = argparse.ArgumentParser(description="Add N deterministic photos/videos to testenv Immich")
    p.add_argument("--count", type=int, required=True, help="total number of dataset files")
    p.add_argument(
        "--video-every", type=int, default=50, help="one video per this many files (0 = none)"
    )
    p.add_argument("--workers", type=int, default=4, help="parallel uploads (default 4)")
    p.add_argument("--queue-timeout", type=int, default=6 * 3600, help="seconds (default 6h)")
    p.add_argument("--no-wait", action="store_true", help="do not wait for Immich job queues")
    args = p.parse_args()
    if args.count < 1:
        sys.exit("error: --count must be 1 or more")

    # 1. seed가 먼저 돼 있어야 한다 (관리자 계정과 refs.json)
    if not seed.REFS.exists():
        sys.exit("error: testenv/refs.json not found. Run make seed first")

    # 2. 데이터셋 준비
    env = seed.load_env()
    image = f"ghcr.io/immich-app/immich-server:{env.get('IMMICH_VERSION', 'release')}"
    paths = ensure_dataset(args.count, args.video_every, image)

    # 3. 로그인 후 업로드
    api = seed.Immich(env.get("IMMICH_URL", "http://localhost:2283"))
    status, body = api.request(
        "POST",
        "/auth/login",
        {"email": env["TESTENV_ADMIN_EMAIL"], "password": env["TESTENV_ADMIN_PASSWORD"]},
    )
    if status not in (200, 201) or not isinstance(body, dict):
        sys.exit(f"error: login failed (HTTP {status})")
    api.token = body["accessToken"]
    dataset_refs = upload_all(api, paths, args.workers)

    # 4. 작업 대기열 대기
    if args.no_wait:
        print("skipped waiting for job queues (--no-wait): back up only after jobs finish")
    else:
        wait_queues(api, args.queue_timeout)

    # 5. refs.json: 샘플 항목은 그대로 두고 데이터셋 항목만 새로 넣는다 (여러 번 실행해도 중복 없음)
    refs = json.loads(seed.REFS.read_text(encoding="utf-8"))
    samples = [a for a in refs["assets"] if not a["filename"].startswith("dataset-")]
    refs["assets"] = samples + dataset_refs
    refs["asset_count"] = len(refs["assets"])
    refs["dataset"] = {
        "version": DATASET.name,
        "count": args.count,
        "videos": sum(1 for r in dataset_refs if r["filename"].endswith(".mp4")),
        "bytes": sum(r["size"] for r in dataset_refs),
    }
    seed.REFS.write_text(json.dumps(refs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"wrote reference file: {seed.REFS.relative_to(HERE.parent)} "
        f"({len(samples)} seed samples + {len(dataset_refs)} dataset files)"
    )
    print("next: make backup")


if __name__ == "__main__":
    main()
