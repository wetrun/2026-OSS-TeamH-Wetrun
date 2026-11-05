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
| `backup.sh` | O | DB 덤프와 restic 백업 |
| `.env` | X | 실제 설정 (`.env.example` 복사본) |
| `docker-compose.yml` | X | Immich 공식 파일. `up.sh`가 `.env`의 `IMMICH_VERSION`으로 준비한다 |
| `docker-compose.<버전>.yml` | X | 받아 둔 공식 파일. 같은 버전이면 다시 받지 않아 네트워크 없이도 `env-up`이 된다 |
| `data/` | X | 사진(`library/`), DB(`postgres/`), 백업 |
| `samples/`, `refs.json` | X | seed.py가 만드는 샘플 사진과 정답지 |

Immich 버전은 `.env.example`의 `IMMICH_VERSION`(현재 v3.3.5)으로 고정한다.
버전을 바꾸려면 팀과 합의한 뒤 이 값만 고친다.

## 자주 겪는 문제

| 증상 | 원인·해결 |
|---|---|
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
