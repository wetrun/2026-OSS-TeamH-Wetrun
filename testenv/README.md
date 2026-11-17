# testenv

개발·평가용 Immich 테스트 환경. 배포 대상이 아니다.
운영 중인 Immich를 흉내 낸 환경으로, 실행기·검사 개발과 평가에 쓴다.

담당: 정순준. 담당 범위와 완료 기준은 [docs/handoff/env.md](../docs/handoff/env.md).

## 필요한 도구

Linux·macOS 터미널, Windows는 WSL2 Ubuntu 안에서 실행한다. 설치 방법은 [온보딩 3절](../docs/onboarding.md#3-개발-환경-준비).

| 도구 | 확인 명령 | 쓰는 곳 | 비고 |
|---|---|---|---|
| Docker + Compose v2 | `docker compose version` | env-up, backup, env-clean | Windows: Docker Desktop의 WSL Integration에서 Ubuntu 켜기 |
| make | `make --version` | 모든 명령 | |
| uv | `uv --version` | seed | Python 3.12는 `make install`(uv sync)이 준비한다 |
| curl | `curl --version` | env-up | compose 파일을 처음 받을 때만 |
| restic | `restic version` | backup | **0.18 이상** (0.18에서 확인). apt 버전은 오래됐다(Ubuntu 22.04: 0.12, 24.04: 0.16). [GitHub 릴리스](https://github.com/restic/restic/releases)에서 받는다 |

스크립트는 시작할 때 도구가 있는지, Docker가 켜져 있는지 확인하고, 없으면 설치·해결 방법을 출력하고 멈춘다.

## 사용법

저장소 루트에서 실행한다.

```sh
make env         # 아래 셋을 차례로: env-up → seed → backup

make env-up      # Immich 받기 → 실행 → healthy 대기
make seed        # 테스트 계정·샘플 사진·앨범 만들기 → refs.json 작성
make backup      # DB 덤프 → restic 백업
make env-down    # 멈추기 (데이터는 남음)
make env-clean   # 멈추고 data/(사진, DB, 백업)까지 삭제. 지우기 전에 [y/N]을 묻는다
make env-clean YES=1   # 묻지 않고 삭제 (스크립트·반복 시험용)
```

`make env-up`이 끝나면 http://localhost:2283 에서 접속한다.
포트는 이 컴퓨터(`127.0.0.1`)에서만 열린다. 다른 기기에서 접속해야 하면 `.env`의 `TESTENV_BIND_ADDR`를 `0.0.0.0`으로 바꾸고 `make env-up`을 다시 한다 (같은 네트워크의 누구나 공개된 테스트 비밀번호로 로그인할 수 있으니 주의).
`make seed` 후에는 `.env.example`의 테스트 계정(`teamh@wetrun.test` / `testpwd`)으로 로그인한다.

## seed가 만드는 데이터

| 항목 | 값 |
|---|---|
| 관리자 | `TESTENV_ADMIN_EMAIL`, `TESTENV_ADMIN_PASSWORD`, `TESTENV_ADMIN_NAME` (`.env.example`) |
| 사진 | `samples/sample-01`~`05` PNG 5장. seed.py가 직접 그린다 (다운로드·라이선스 없음, 누가 만들어도 같은 바이트) |
| 앨범 | `TESTENV_ALBUM_NAME`(`testenv-album`)에 앞의 3장 |
| `refs.json` | 정답지: 사진별 파일 이름·SHA-1·크기·asset id, 앨범 이름·사진 수. 비밀번호는 넣지 않는다 |

여러 번 실행해도 된다. 이미 있는 관리자·사진·앨범은 그대로 쓴다.
asset id와 앨범 id는 환경마다 다르다. 파일 비교는 SHA-1로 한다.

## 대용량 평가 데이터 (seed-dataset)

복구·검사 시간이 데이터 개수에 따라 어떻게 늘어나는지 재기 위해 데이터셋 N개(JPEG 사진 + MP4 동영상)를 더 넣는다.
휴대폰 사진·동영상의 형식·용량을 흉내 내서, 실제 크기 파일의 다운로드·복원 시간을 잴 수 있게 했다.

```sh
make env-up                 # Immich 서버 이미지가 있어야 한다 (그 안의 ffmpeg로 JPEG·MP4를 만든다)
make seed                   # 관리자·샘플 5장·앨범 (seed-dataset은 이걸 하지 않는다)
make seed-dataset N=295     # 데이터셋 295개 생성·업로드 + Immich 작업 대기 + refs.json에 추가 → 전체 300개
make backup
# 다음 단계: N=1495(전체 1500), N=2995(전체 3000). 이미 올린 파일은 duplicate로 건너뛰고 나머지만 올린다
```

| 항목 | 값 |
|---|---|
| 사진 | `dataset/v3/dataset-NNNNNN.jpg`. 4032x3024(1200만 화소) JPEG, 장당 약 2.7 / 3.7 / 5.2MB (품질 3단계를 번호로 정함) |
| 동영상 | 50개 중 1개(49, 99, …번)가 `.mp4`. 1920x1080 30fps H.264, 16Mbps로 5~15초 → 약 10~30MB. 295개면 5개, 1495개면 29개, 2995개면 59개 |
| 내용 | ffmpeg 테스트 화면(testsrc2) + 잡음. 파일마다 잡음이 달라 restic이 중복으로 합치지 못하고, 이미 압축된 형식이라 restic 압축으로도 줄지 않는다 |
| 같은 바이트 | Immich 서버 이미지(`IMMICH_VERSION`) 안의 ffmpeg를 `docker run`으로 쓴다. 버전이 같으면 누가 만들어도 같은 파일이다 |
| 용량 | 평균 약 3.9MB/개: 295개 약 1.2GB, 1495개 약 6GB, 2995개 약 12GB. 디스크는 원본·library·restic·복구본으로 약 4배 필요 |
| 생성 시간 | 사진 100장에 약 15~20초, 동영상 1개에 약 5~10초 (PC마다 다름). 한 번 만든 파일은 다시 만들지 않는다 |
| 촬영 시각 | 2025-01-01T00:00Z + 번호 x 1분 (샘플 5장과 겹치지 않음) |
| `refs.json` | 샘플 5장 뒤에 데이터셋 항목이 붙고, `dataset`(버전·개수·동영상 수·바이트)이 기록된다. 다시 실행하면 데이터셋 항목만 새로 바꾼다. 검사 결과의 파일 수는 샘플 5장을 더한 값이다 |
| 대기 | 업로드 뒤 `GET /api/queues`의 남은 작업이 0이 될 때까지 기다린다 (기본 최대 6시간, `--queue-timeout`). 동영상 트랜스코딩 때문에 사진만 있을 때보다 오래 걸린다 |

옵션은 `uv run python testenv/seed_dataset.py --help`에서 본다 (`--video-every`, `--workers`, `--no-wait`).
생성 방식이 바뀌면 `dataset/` 아래 폴더 이름(`v3`)을 바꾼다. 예전 방식으로 올린 Immich에 이어서 넣지 말고 `make env-clean YES=1`부터 다시 한다.
`dataset/`은 커밋하지 않는다 (`.gitignore`).

## backup이 만드는 백업

| 항목 | 값 |
|---|---|
| 저장소 | `testenv/data/restic-repo` (`RESTIC_REPOSITORY`) |
| 비밀번호 | `resticpwd` (`RESTIC_PASSWORD`, testenv 전용) |
| 태그·호스트 | `testenv` / `testenv` (누가 만들어도 같게 고정) |
| 내용 | `data/backup/immich.sql`(pg_dumpall 덤프), `data/library/`(사진 원본·썸네일 등) |

DB는 실행 중인 파일을 그대로 복사하지 않고 덤프를 떠서 백업한다.
`make backup`을 다시 실행하면 스냅샷이 하나 더 쌓인다.
`refs.json`은 백업에 넣지 않는다 (복구 결과와 비교할 바깥의 정답지).

직접 확인하려면 (`testenv/`에서):

```sh
export RESTIC_REPOSITORY=./data/restic-repo RESTIC_PASSWORD=resticpwd
restic snapshots
restic restore latest --target /tmp/restore-test   # /tmp/restore-test/data/... 로 풀린다
```

## 구성

| 파일 | 커밋 | 내용 |
|---|---|---|
| `.env.example` | O | 설정 예시. 처음 실행할 때 `.env`로 복사된다 |
| `up.sh`, `down.sh` | O | 실행·정리 스크립트 |
| `common.sh` | O | 스크립트 공통 함수 (도구 확인, `.env` 읽기) |
| `seed.py` | O | 테스트 데이터 넣기, `refs.json` 작성 (표준 라이브러리만 사용) |
| `seed_dataset.py` | O | 대용량 평가용 JPEG·MP4 N개 추가 (`make seed-dataset N=...`) |
| `backup.sh` | O | DB 덤프와 restic 백업 |
| `.env` | X | 실제 설정 (`.env.example` 복사본) |
| `docker-compose.yml` | X | Immich 공식 파일. `up.sh`가 `.env`의 `IMMICH_VERSION`으로 준비한다 |
| `docker-compose.<버전>.yml` | X | 받아 둔 공식 파일. 같은 버전이면 다시 받지 않아 네트워크 없이도 `env-up`이 된다 |
| `data/` | X | 사진(`library/`), DB(`postgres/`), 백업 |
| `samples/`, `refs.json` | X | seed.py가 만드는 샘플 사진과 정답지 |
| `dataset/` | X | seed_dataset.py가 만드는 대용량 평가용 사진·동영상 |

Immich 버전은 `.env.example`의 `IMMICH_VERSION`(현재 v3.3.5)으로 고정한다.
버전을 바꾸려면 팀과 합의한 뒤 이 값만 고친다.

## 자주 겪는 문제

| 증상 | 원인·해결 |
|---|---|
| 처음 `make env`에서 `container ... immich-server-1 is unhealthy`로 멈춤 | 처음 기동할 때는 DB 초기화가 늦어 서버가 잠시 unhealthy로 잡힐 수 있다. 1~2분 뒤 `docker compose ps`로 healthy인지 확인하고 `make seed backup`을 이어서 실행한다 |
| `wetrun run`을 돌리면 서비스가 종료 코드 137로 죽음 | 메모리 부족. 검증용 Immich가 하나 더 뜨므로, testenv Immich(약 1.5GB)와 함께 돌리려면 그만큼 여유가 필요하다. 부족하면 `make env-down` 후 실행한다 |
| `data/`에서 `Permission denied` | Docker가 `data/`를 먼저 만들어 root 소유가 됨. `up.sh`는 폴더를 먼저 만들어 이를 막는다. 이미 생겼다면 `sudo chown "$USER": testenv/data` (`-R` 금지: Postgres가 켜지지 않는다) |
| `failed to download docker-compose.yml` | 처음 실행이나 버전을 바꾼 직후에만 GitHub에 접속한다. VPN을 끄거나 다른 네트워크에서 재시도 |
| `cannot connect to Docker` | Docker Desktop이 꺼져 있거나 WSL Integration에서 Ubuntu가 꺼져 있음 |
| `make seed`에서 `login failed` | 웹에서 다른 계정으로 관리자를 먼저 만들었음. `make env-clean` 후 `make env-up`, `make seed` |
| 예전에 만든 `.env`에 새 설정(`TESTENV_*`, `RESTIC_*`)이 없음 | 괜찮다. 스크립트는 `.env.example` 값을 기본으로 쓰고 `.env` 값으로 덮어쓴다 |
| `removed Windows line endings (\r) from .env` | Windows 편집기로 `.env`를 저장하면 줄 끝에 `\r`이 붙어 버전·비밀번호가 깨진다. 스크립트가 자동으로 지운다 |
| `cannot open restic repository` | `.env`의 `RESTIC_PASSWORD`가 저장소를 만들 때와 다름. 원래 값으로 되돌리거나, 시험용이면 `make env-clean` 후 다시 `make env` |
| `cannot ask for confirmation` | `make env-clean`을 입력을 받을 수 없는 곳(스크립트 등)에서 실행함. `make env-clean YES=1` |
| `make backup`에서 `Immich DB is not running` | `make env-up`을 먼저 실행 |
| restic 버전에 따라 복원 경로가 다름 | restic 0.18은 상대 경로로 백업하면 `--target` 아래 `data/...`로 풀린다 |
| 앨범을 열면 `Not found or no album.read access` | 데이터를 지우기 전의 앨범 주소. http://localhost:2283 으로 다시 접속 |
| `Conflict. The container name "/immich_server" is already in use` | 공식 compose가 컨테이너 이름을 고정해서 한 컴퓨터에 Immich를 하나만 띄울 수 있다. 다른 Immich가 떠 있는지 `docker ps`로 확인. 프로젝트 이름을 바꾸기 전에 띄운 testenv라면 `cd testenv && docker compose -p immich down` |
| `.env`를 읽을 때 `command not found` | `.env` 값에 공백이 있으면 따옴표로 감싼다. 예: `TESTENV_ADMIN_NAME="Wetrun Admin"` |
