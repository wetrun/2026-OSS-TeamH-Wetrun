# 2026-OSS-Wetrun

2026 공개소프트웨어 프로젝트 Team H

기존 restic 백업으로 Docker Compose 서비스를 운영과 분리된 환경에 실제로 복구해 보고,
로그인·조회·다운로드 같은 사용자 동작까지 검사하는 도구. 첫 대상 서비스는 Immich.

> 개발 중 (v0.1 목표: 2026-12)

## 개발 시작

Linux·macOS 터미널에서 실행한다. **Windows는 WSL2 Ubuntu 안에서** 실행하고, 저장소는 WSL 홈(`~/`)에
clone한다 (`/mnt/c` 아래 금지). 필요 도구: Docker(Compose v2), restic, uv, make.
설치 방법은 [온보딩 3절](docs/onboarding.md#3-개발-환경-준비).

```sh
make install      # uv sync
make lint test
```

처음이라면 [docs/onboarding.md](docs/onboarding.md)부터. 규칙은 [CONTRIBUTING.md](CONTRIBUTING.md).

## 사용

Linux와 Docker(Compose v2), restic 0.18 이상이 필요하다. 워크플로 예시는 [`profiles/immich/workflow.yaml`](profiles/immich/workflow.yaml),
작성 규칙은 [docs/contract.md](docs/contract.md).

```sh
export RESTIC_PASSWORD=...                          # 워크플로의 env: 참조 값
uv run wetrun check-input profiles/immich/workflow.yaml   # 아무것도 띄우지 않고 입력만 검사
uv run wetrun run profiles/immich/workflow.yaml           # 복구·검사 후 요약 출력
```

- 종료 코드: `0` 통과, `1` 백업·복구 문제(`fail`), `2` 입력·환경 문제(`error`), `3` 정리 실패
- JSON 리포트는 `~/.local/share/wetrun/runs/`에 쌓인다 (`WETRUN_REPORT_DIR`).
- 검증하는 동안 서비스 하나만큼의 메모리와, 복원할 백업 크기만큼의 디스크가 더 필요하다. 운영 서버가 빠듯하면 다른 컴퓨터에서 돌린다.
- 매일 자동 실행: `uv run wetrun schedule <workflow.yaml> --at 03:30 --env-file <비밀 값 파일>`이 출력하는 줄을 `crontab -e`에 붙여 넣는다. 같은 워크플로는 동시에 하나만 실행된다.
- macOS 개발 환경은 [docs/handoff/runner.md](docs/handoff/runner.md)의 `WETRUN_WORKDIR` 안내를 본다.

## 구조

| 경로 | 내용 |
|---|---|
| `wetrun/` | 도구 본체 (실행기, restic 어댑터, 내장 단계, 리포트·알림). 서비스 이름 없음 |
| `profiles/<서비스>/` | 서비스별 워크플로 YAML과 검사 컨테이너 |
| `testenv/` | 개발·평가용 Immich 환경 (배포 대상 아님) |
| `faults/` | 고장 백업 생성 스크립트와 예상 탐지 단계 |
| `tests/` | 단위·계약·격리 테스트 |
| `eval/` | 평가 스크립트와 결과 |
| `docs/` | 계약, 수동 복구 절차, 워크플로 작성법, 지원 버전 |

## 라이선스

Apache-2.0
