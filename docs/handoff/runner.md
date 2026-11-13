# handoff: 실행기 (차은호)

담당: `wetrun/` (단, `steps/`·`report.py`·`notify.py` 제외)

검사 담당과의 계약: [docs/contract.md](../contract.md) (검사 컨테이너 입출력, 워크플로 YAML, 판정 규칙, 종료 코드).

## 현재 상태 (2026-11-14)

| 부분 | 파일 | 상태 |
|---|---|---|
| 판정 함수, 결과 형식 | `contract.py` | 완료 (#10, #12) |
| 격리 변환, 정리 | `isolation.py` | 완료 (#11) |
| 입력 검사 `wetrun check-input` | `workflow.py` | 완료 (#15) |
| restic 연동 | `restic.py` | 완료 (#16) |
| 실행 본체 `wetrun run` | `runner.py` | 리뷰 중 (#17) |
| 예약 실행, 중복 실행 방지 | `schedule.py` | 시작 전 |

## 실행 방법

```sh
export RESTIC_PASSWORD=...                # 워크플로의 env: 참조 값
export WETRUN_WORKDIR=~/.cache/wetrun     # 실행 디렉터리 위치 (기본 /var/tmp/wetrun)
uv run wetrun check-input workflow.yaml   # 아무것도 띄우지 않고 입력만 검사
uv run wetrun run workflow.yaml           # 결과 JSON을 출력하고 종료 코드 0/1/2/3
```

- **실행 디렉터리:** 복원한 데이터가 들어가므로 공간이 넉넉한 곳으로 지정한다. 실행이 끝나면 지워진다.
- **macOS:** Colima나 Docker Desktop은 공유하지 않은 경로를 마운트하면 오류 없이 빈 폴더를 넣는다. Colima는 기본으로 홈 폴더만 공유한다. 그래서 `WETRUN_WORKDIR`를 홈 아래로 지정한다. 지정하지 않으면 실행 전에 "Docker가 실행 디렉터리를 볼 수 없음"으로 멈춘다.
- **결과 출력:** `report.py`가 생기기 전까지 결과(`RunResult`)를 JSON 그대로 출력한다.

## 실제 Immich로 시험한 결과 (#13 코멘트)

testenv 백업으로 끝까지 돌렸다. macOS + Colima, Immich v3.3.5, restic 0.19.1.

| 백업 | 결과 | 판정 단계 |
|---|---|---|
| 정상 | `pass`, 70초 (복원 2, DB 기동 6, 덤프 복원 27, 전체 기동 33, 응답 1) | - |
| DB 덤프 손상 | `fail` | `exec` (psql 종료 코드 3) |
| DB 덤프 누락 | `fail` | `exec` (입력 파일 없음) |

## 정한 것과 근거

검토한 선택지와 고민 과정은 [design-decisions.md](../design-decisions.md).

| 결정 | 근거 |
|---|---|
| 검사는 실행기와 같은 uid로 실행 | #11 코멘트 |
| 검사는 `timeout` 안에 끝내고, 실행기는 `timeout`+30초에 끊음 | #12 |
| 실행기 단계 판정: 백업 내용 문제면 `fail`, 환경·입력 문제면 `error` | #13 |
| restic은 복원 전에 환경 원인을 거르고, 그 뒤의 실패는 `fail`. 스냅샷 없음도 `fail` | #16, #13 코멘트 |
| 검사 컨테이너: 소스를 `/opt/wetrun`에 읽기 전용 마운트, `python:3.12-slim`, compose `default` 네트워크 | #17 |
| `env_file`은 실행 디렉터리에 같은 이름으로 복사 | #17, #13 코멘트 |
| `/etc/localtime`·`/etc/timezone`은 읽기 전용일 때만 마운트 허용 | #17, #13 코멘트 |
| 검증 서비스마다 메모리 상한, 메모리 부족은 `error` | #17, #13 코멘트 |
| Docker가 실행 디렉터리를 못 보면 실행 전에 `error` | #17 |

## 알려진 한계

- **메모리:** 검증 중에는 서비스 하나만큼 메모리가 더 필요하다.
  - 서비스마다 상한(기본 `2g`, `compose.mem_limit`)이 있어, 넘치면 검증 컨테이너만 죽는다. 메모리 부족으로 실패한 단계는 `error`로 판정한다 (#17).
  - 합계는 묶지 않으므로, 합계가 넘치면 여전히 전역 OOM이 날 수 있다.
  - Immich는 ML을 띄우지 않으면 약 35% 줄어든다 (#13).
- **확인하지 못한 것**
  - Linux에서 직접 실행 (지금까지 macOS + Colima에서만 시험)
  - root 소유 파일 복원
  - 오래된 Compose에 `--wait-timeout`이 있는지
- **중복 실행 방지가 없다.** 실행마다 프로젝트 이름이 달라 겹쳐도 안전하다. 예약 실행을 만들 때 추가한다.
- **오프라인:** `alpine:3`(Docker 확인·정리용)과 `python:3.12-slim`(검사용)을 미리 받아 둬야 한다.

## 테스트

- 단위 시험은 `make test`로 돈다.
- `tests/integration/`은 restic과 Docker가 있어야 하고, 없으면 건너뛴다.
- macOS에서 통합 시험을 돌릴 때도 공유된 경로가 필요하다.

```sh
WETRUN_WORKDIR=~/.cache/wetrun-test uv run pytest tests/integration
```

## 다음 작업

1. #13 합의 후 `contract.md` 4절에 실행기 단계 판정 규칙을 추가
2. Linux에서 확인: root 실행, root 소유 파일 복원
3. 예약 실행: cron/systemd, 중복 실행 방지(락), restic에 필요한 `$HOME`
4. 실행 이력으로 timeout 자동 조정, "평소보다 느림" 경고. 리포트 저장 형식이 정해진 뒤 한다
