# testenv

개발·평가용 Immich 테스트 환경. 배포 대상이 아니다.
운영 중인 Immich를 흉내 낸 환경으로, 실행기·검사 개발과 평가에 쓴다.

담당: 정순준. 담당 범위와 완료 기준은 [docs/handoff/env.md](../docs/handoff/env.md).

## 필요한 도구

Linux·macOS 터미널, Windows는 WSL2 Ubuntu 안에서 실행한다. 설치 방법은 [온보딩 3절](../docs/onboarding.md#3-개발-환경-준비).

| 도구 | 확인 명령 | 쓰는 곳 | 비고 |
|---|---|---|---|
| Docker + Compose v2 | `docker compose version` | env-up, env-clean | Windows: Docker Desktop의 WSL Integration에서 Ubuntu 켜기 |
| make | `make --version` | 모든 명령 | |
| curl | `curl --version` | env-up | compose 파일을 처음 받을 때만 |

스크립트는 시작할 때 도구가 있는지, Docker가 켜져 있는지 확인하고, 없으면 설치·해결 방법을 출력하고 멈춘다.

## 사용법

저장소 루트에서 실행한다.

```sh
make env-up      # Immich 받기 → 실행 → healthy 대기
make env-down    # 멈추기 (데이터는 남음)
make env-clean   # 멈추고 data/(사진, DB, 백업)까지 삭제. 지우기 전에 [y/N]을 묻는다
make env-clean YES=1   # 묻지 않고 삭제 (스크립트·반복 시험용)
```

`make env-up`이 끝나면 http://localhost:2283 에서 접속한다.

## 구성

| 파일 | 커밋 | 내용 |
|---|---|---|
| `.env.example` | O | 설정 예시. 처음 실행할 때 `.env`로 복사된다 |
| `up.sh`, `down.sh` | O | 실행·정리 스크립트 |
| `common.sh` | O | 스크립트 공통 함수 (도구 확인, `.env` 읽기) |
| `.env` | X | 실제 설정 (`.env.example` 복사본) |
| `docker-compose.yml` | X | Immich 공식 파일. `up.sh`가 `.env`의 `IMMICH_VERSION`으로 준비한다 |
| `docker-compose.<버전>.yml` | X | 받아 둔 공식 파일. 같은 버전이면 다시 받지 않아 네트워크 없이도 `env-up`이 된다 |
| `data/` | X | 사진(`library/`), DB(`postgres/`), 백업 |

Immich 버전은 `.env.example`의 `IMMICH_VERSION`(현재 v3.3.5)으로 고정한다.
버전을 바꾸려면 팀과 합의한 뒤 이 값만 고친다.

## 자주 겪는 문제

| 증상 | 원인·해결 |
|---|---|
| `data/`에서 `Permission denied` | Docker가 `data/`를 먼저 만들어 root 소유가 됨. `up.sh`는 폴더를 먼저 만들어 이를 막는다. 이미 생겼다면 `sudo chown "$USER": testenv/data` (`-R` 금지: Postgres가 켜지지 않는다) |
| `failed to download docker-compose.yml` | 처음 실행이나 버전을 바꾼 직후에만 GitHub에 접속한다. VPN을 끄거나 다른 네트워크에서 재시도 |
| `cannot connect to Docker` | Docker Desktop이 꺼져 있거나 WSL Integration에서 Ubuntu가 꺼져 있음 |
| `removed Windows line endings (\r) from .env` | Windows 편집기로 `.env`를 저장하면 줄 끝에 `\r`이 붙어 버전·비밀번호가 깨진다. 스크립트가 자동으로 지운다 |
| `cannot ask for confirmation` | `make env-clean`을 입력을 받을 수 없는 곳(스크립트 등)에서 실행함. `make env-clean YES=1` |
| `Conflict. The container name "/immich_server" is already in use` | 공식 compose가 컨테이너 이름을 고정해서 한 컴퓨터에 Immich를 하나만 띄울 수 있다. 다른 Immich가 떠 있는지 `docker ps`로 확인. 프로젝트 이름을 바꾸기 전에 띄운 testenv라면 `cd testenv && docker compose -p immich down` |
| `.env`를 읽을 때 `command not found` | `.env` 값에 공백이 있으면 따옴표로 감싼다. 예: `TESTENV_ADMIN_NAME="Wetrun Admin"` |
