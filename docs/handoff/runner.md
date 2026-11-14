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
| 실행 본체 `wetrun run` | `runner.py` | 완료 (#17) |
| 리포트 저장·요약·알림 연결 | `__main__.py` | 완료 (#29) |
| 예약 실행(crontab 줄 생성), 중복 실행 방지 | `schedule.py`, `__main__.py` | 완료 (#31) |

## 실행 방법

```sh
export RESTIC_PASSWORD=...                # 워크플로의 env: 참조 값
export WETRUN_WORKDIR=~/.cache/wetrun     # 실행 디렉터리 위치 (기본 /var/tmp/wetrun)
uv run wetrun check-input workflow.yaml   # 아무것도 띄우지 않고 입력만 검사
uv run wetrun run workflow.yaml           # 요약을 출력하고 종료 코드 0/1/2/3
uv run wetrun schedule workflow.yaml --at 03:30 --env-file ~/.config/wetrun.env   # crontab 줄 출력
```

- **예약 실행:** cron은 환경이 거의 비어 있어서, 출력되는 줄에 PATH, `--env-file`의 비밀 값(`KEY=VALUE`, 본인만 읽게 0600), 로그 위치(`~/.local/share/wetrun/cron.log`)가 들어 있다. restic이 쓰는 `HOME`은 cron이 넣어 준다.
- **중복 실행 방지:** `wetrun run`은 워크플로마다 잠금을 잡는다. 같은 워크플로가 이미 돌고 있으면 종료 코드 `2`로 멈춘다. 잠금 파일은 임시 폴더(`wetrun-locks-<uid>`)에 있고, 프로세스가 죽으면 운영체제가 푼다.

- **실행 디렉터리:** 복원한 데이터가 들어가므로 공간이 넉넉한 곳으로 지정한다. 실행이 끝나면 지워진다.
- **macOS:** Colima나 Docker Desktop은 공유하지 않은 경로를 마운트하면 오류 없이 빈 폴더를 넣는다. Colima는 기본으로 홈 폴더만 공유한다. 그래서 `WETRUN_WORKDIR`를 홈 아래로 지정한다. 지정하지 않으면 실행 전에 "Docker가 실행 디렉터리를 볼 수 없음"으로 멈춘다.
- **결과 출력:** 요약을 출력하고 JSON 리포트를 `$WETRUN_REPORT_DIR`(기본 `~/.local/share/wetrun/runs/`)에 저장한다. 알림은 `notify:` 설정이 있을 때만 (contract 5절).

## 실제 Immich로 시험한 결과 (#13 코멘트)

testenv 백업으로 끝까지 돌렸다. macOS + Colima, Immich v3.3.5, restic 0.19.1. Linux에서도 같은 결과다(아래 알려진 한계).

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
- **일반 사용자로 복원하면 파일 소유자가 유지되지 않는다.** 서비스가 root로 만든 파일도 오류 없이 복원되지만, 소유자는 복원한 사용자가 된다 (#20). DB 데이터 폴더를 그대로 백업하는 서비스는 소유자가 달라 뜨지 않을 수 있으니 root로 실행한다. 덤프로 복원하는 Immich는 문제없다.
- **Linux 확인 (CI, ubuntu 러너):** 실행기 통합 시험, 검사 컨테이너의 파일 권한(#11), root로 실행할 때 검사 파일 소유자 변경, root 소유 파일 복원 (#17, #20)
- **실제 Linux 기기에서 확인 (Ubuntu 26.04, Docker 29.1, Compose 2.40.3, restic 0.18.0):**
  - 전체 시험 통과
  - testenv Immich를 켜 둔 채로 검증해도 충돌하지 않았다
  - 사진 파일이 root 소유인 실제 백업도 결과가 macOS와 같았다: 정상 `pass`(53초), 덤프 손상·누락 `fail`
  - 정리 후 남은 자원 없음
- **오래된 Compose (#35):** Docker 24.0.9 + Compose 2.16.0 조합(Docker-in-Docker)에서 실행기 통합 시험이 통과했다. Compose 2.16 클라이언트는 Docker 25 이상 엔진에 접속하지 못하므로(API 1.44 미만 거부), 옛 Compose는 옛 엔진과 함께 쓰는 경우만 의미가 있다
- **중복 실행 방지가 없다.** 실행마다 프로젝트 이름이 달라 겹쳐도 안전하다. 예약 실행을 만들 때 추가한다.
- **오프라인:** `alpine:3`(Docker 확인·정리용)과 `python:3.12-slim`(검사용)을 미리 받아 둬야 한다.

## 테스트

- 단위 시험은 `make test`로 돈다.
- `tests/integration/`은 restic과 Docker가 있어야 하고, 없으면 건너뛴다.
- macOS에서 통합 시험을 돌릴 때도 공유된 경로가 필요하다.

```sh
WETRUN_WORKDIR=~/.cache/wetrun-test uv run pytest tests/integration
```

## v0.1 확인 결과 (#30)

desktop Linux에서 `profiles/immich/workflow.yaml`(`ref_files` 포함)로 돌렸다.

| 백업 | 결과 |
|---|---|
| 정상 | `pass`, 53초 |
| 사진 누락 | `fail` |
| 사진 손상 | `fail` |
| DB 덤프 손상 | `fail` |
| DB 덤프 누락 | `fail` |

cron과 같은 빈 환경에서 `wetrun schedule`이 만든 줄로도 통과했다.

## 다음 작업 (v0.1 이후)

1. 실행 이력으로 timeout 자동 조정, "평소보다 느림" 경고, 시작 전 메모리 여유 확인 ([design-decisions.md](../design-decisions.md) 4·8절)
   - 리포트에 워크플로를 구별할 값과 "시간 초과로 끊김" 표시가 필요하다 (계약 변경, 리포트 담당과 합의)
   - 예약 실행으로 이력이 쌓인 뒤 계수를 정한다
2. systemd timer (필요해지면)

실행이 아예 돌지 않은 경우는 잡지 않기로 했다. 근거는 [design-decisions.md](../design-decisions.md) 12절.
