# handoff: 환경·성능·사용자 평가·문서 (정순준)

## 맡는 범위

누구나 명령 한 줄로 같은 Immich + 백업 상태를 만들 수 있는 테스트 환경, 그리고 성능·사용자 평가와 문서.

- `testenv/` 개발·평가용 Immich 환경 (배포 대상 아님)
- `docs/manual-restore.md` 수동 복구 절차
- `eval/` 성능 측정, 사용자 평가 (고장 시나리오 평가는 김영모)
- 사용자 문서: 설치, 백업 준비, 지원 버전 (`docs/supported-versions.md`)

**이 작업이 끝나야 실행기·검사 개발이 시작된다.** 막히면 바로 공유한다.

## 일정

| 단계 | 할 일 |
|---|---|
| M0 (~11/6) | 11/4 `env-up` + `seed` · 11/5 `backup` · 11/6 수동 복구 1회 성공·절차 문서화 (김영모와) |
| M1 (~11/12) | 원격 저장소 1종(rest-server 또는 S3 호환) 구성, 같은 스냅샷 복원 확인 |
| M2 (~11/18) | 사진 수천 장 규모 대용량 데이터셋 준비 |
| M3 (~11/22) | 평가 계획 확정 (김영모와): 지표, 반복 횟수, 사용자 평가 절차·참여자 |
| M4 (~11/28) | 전체 복원 대비 L0+L2 방식의 디스크·시간 측정 · 사용자 평가 2~3명 (수동 절차 vs 도구: 첫 성공 시간, 설정 오류, 도움 요청, 개입 횟수) |
| M5 (~12/3) | 사용 설명서·지원 버전 문서 (조정민과) · 발표자료 수정 (김영모와) |

## testenv 요구사항

`testenv/` 폴더에 만들 것:

1. `compose.yaml` 대신 **공식 compose를 내려받아 쓴다.** Immich는 AGPL-3.0이라 파일을 repo에 복사하지 않는다.
   `make env-up`이 `IMMICH_VERSION` 태그의 공식 `docker-compose.yml`을 내려받고, 우리 변경은
   `compose.override.yaml`로 덮어쓴다 (아래 부록). 이미지 태그는 `release`가 아니라 특정 버전으로 고정.
   machine-learning 컨테이너는 끈다 (무겁고 검증에 필요 없음).
2. `.env.example`: 변수 목록만. 실제 `.env`는 커밋하지 않는다 (부록).
3. `gen_dataset.py`: 테스트 사진 생성기 (부록). 기준 사진 5장은 `--seed ref`로 고정 생성.
4. `seed.py`: 표준 라이브러리(urllib)만 사용. Immich API로 관리자·검사 계정 생성,
   기준 사진 업로드, `refs.json`(사진마다 asset ID, 스냅샷 안 경로, sha1) 생성.
   **`refs.json` 필드는 검사 컨테이너 계약과 맞춰야 하니 조정민·차은호와 확인한다.**
5. `backup.py`: Immich 공식 문서 방식으로 DB 덤프 → 원본 사진 폴더·덤프·compose·`.env`를 restic 스냅샷 하나로 백업.
   Mac의 BSD 도구와 옵션 차이를 피하려고 bash 대신 Python으로 쓴다.
6. `Makefile`에 타깃 추가: `env-up`, `env-down`, `env-reset`, `samples`, `seed`, `backup`, `dataset` (부록)

`.gitignore`에는 이미 `testenv/.env`, `data/`, `samples/`, `dataset/`, `refs.json`, `docker-compose.yml`이 들어 있다.

### 완료 기준

- 새로 clone → `cp testenv/.env.example testenv/.env` → `make env-up seed backup`이 오류 없이 끝남
- `restic snapshots`에 스냅샷 1개, `refs.json` 생성
- `make env-reset`으로 처음 상태로 돌아감
- 수동 복구로 로그인 → 기준 사진 다운로드 → 해시 일치
- 완료 후 `docs/onboarding.md`의 저장소 받기 절에 `make env-up seed backup` 추가

### 주의

- Immich는 checksum으로 중복을 걸러낸다. 대용량 데이터셋은 사진마다 내용이 달라야 한다 (`gen_dataset.py`는 seed별 노이즈라 해결됨).
- Apple Silicon Mac에서 Immich 서버·DB 이미지가 arm64를 지원하는지 M0에 확인한다.
- 대용량 측정은 Docker Desktop(Windows·Mac)이 아니라 Linux 머신에서 한다. bind mount가 느려 수치가 왜곡된다.
- 검증용 compose 프로젝트 이름은 `wetrun-testenv`로 고정해 실제 Immich와 겹치지 않게 한다.

## 부록

### compose.override.yaml

```yaml
# Immich 공식 docker-compose.yml(make env-up이 고정 버전으로 내려받음) 위에 덮어쓰는 개발용 설정.
services:
  immich-machine-learning:
    profiles: ["ml"] # 기본 기동에서 제외. 필요하면 --profile ml
```

### .env.example

```sh
# cp testenv/.env.example testenv/.env 후 값 채우기. 실제 .env는 커밋하지 않는다.

# --- Immich (공식 .env 변수) ---
# 특정 릴리스 태그로 고정 (예: v2.x.y). M0에서 확정해 docs/supported-versions.md에 기록.
IMMICH_VERSION=
UPLOAD_LOCATION=./data/library
DB_DATA_LOCATION=./data/postgres
TZ=Asia/Seoul
DB_USERNAME=postgres
DB_PASSWORD=
DB_DATABASE_NAME=immich

# --- testenv (seed·backup 스크립트용) ---
RESTIC_REPOSITORY=./data/restic-repo
RESTIC_PASSWORD=
WETRUN_ADMIN_EMAIL=admin@example.test
WETRUN_ADMIN_PASSWORD=
WETRUN_TEST_EMAIL=wetrun@example.test
WETRUN_TEST_PASSWORD=
```

### Makefile 타깃

```make
ENV_FILE := testenv/.env
IMMICH_VERSION ?= $(shell grep -E '^IMMICH_VERSION=' $(ENV_FILE) 2>/dev/null | cut -d= -f2)
COMPOSE := docker compose -p wetrun-testenv --env-file $(ENV_FILE) \
	-f testenv/docker-compose.yml -f testenv/compose.override.yaml
N ?= 3000

# Immich 공식 compose를 고정 버전으로 내려받음 (AGPL 파일을 repo에 복사하지 않기 위해)
testenv/docker-compose.yml:
	@test -n "$(IMMICH_VERSION)" || { echo "testenv/.env에 IMMICH_VERSION을 넣으세요"; exit 1; }
	curl -fsSL -o $@ https://github.com/immich-app/immich/releases/download/$(IMMICH_VERSION)/docker-compose.yml

env-up: testenv/docker-compose.yml
	$(COMPOSE) up -d --wait

env-down:
	$(COMPOSE) down

env-reset:
	$(COMPOSE) down -v
	rm -rf testenv/data testenv/samples testenv/refs.json

samples:
	python3 testenv/gen_dataset.py 5 --seed ref --out testenv/samples

seed: samples
	uv run python testenv/seed.py

backup:
	uv run python testenv/backup.py

dataset:
	python3 testenv/gen_dataset.py $(N) --mb 3 --out testenv/dataset
```

`--check`로 생성기 자체 검증: `python3 testenv/gen_dataset.py --check`. CI에도 이 줄을 추가한다.

### gen_dataset.py

```python
#!/usr/bin/env python3
"""테스트 사진 생성: 서로 다른 노이즈 PNG N장. 표준 라이브러리만 사용.

노이즈는 압축되지 않아 파일 크기를 맞출 수 있고, 내용이 모두 달라
Immich의 checksum 중복 제거에 걸리지 않는다. 같은 seed는 같은 파일을 만든다.
"""

import argparse
import math
import random
import struct
import zlib
from pathlib import Path

SIG = b"\x89PNG\r\n\x1a\n"


def chunk(kind: bytes, data: bytes) -> bytes:
    crc = struct.pack(">I", zlib.crc32(kind + data))
    return struct.pack(">I", len(data)) + kind + data + crc


def png(w: int, h: int, randbytes) -> bytes:
    raw = b"".join(b"\x00" + randbytes(w * 3) for _ in range(h))  # 행마다 filter 0 + RGB
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return SIG + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 1)) + chunk(b"IEND", b"")


def check() -> None:
    d = png(4, 3, random.Random(1).randbytes)
    assert d[:8] == SIG and d[12:16] == b"IHDR"
    n = struct.unpack(">I", d[33:37])[0]
    assert d[37:41] == b"IDAT" and len(zlib.decompress(d[41 : 41 + n])) == 3 * (1 + 4 * 3)
    assert png(4, 3, random.Random(1).randbytes) == d  # 같은 seed → 같은 파일
    print("ok")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("count", type=int, nargs="?", default=0)
    p.add_argument("--mb", type=float, default=3.0, help="장당 대략 크기(MB)")
    p.add_argument("--out", type=Path, default=Path("dataset"))
    p.add_argument("--seed", default="0")
    p.add_argument("--check", action="store_true", help="자체 검증만 실행")
    a = p.parse_args()
    if a.check:
        check()
        raise SystemExit
    side = int(math.sqrt(a.mb * 1_000_000 / 3))
    a.out.mkdir(parents=True, exist_ok=True)
    for i in range(a.count):
        r = random.Random(f"{a.seed}-{i}")
        (a.out / f"img_{i:05d}.png").write_bytes(png(side, side, r.randbytes))
```
