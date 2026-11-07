# 실행기·검사 계약

실행기(`wetrun/`)와 검사(`wetrun/steps/`, `profiles/`)가 따로 개발해도 맞물리도록 정한 약속.
코드의 기준은 [`wetrun/contract.py`](../wetrun/contract.py). 바꿀 때는 실행기·검사 담당이 함께 합의한다.

## 1. 검사는 검사 컨테이너 안에서 실행한다

복구한 서비스는 바깥과 끊긴(`internal`) 네트워크에 포트 없이 뜬다. 그래서 호스트에서는 접속할 수 없다.
검사는 실행기가 같은 네트워크에 띄운 **검사 컨테이너** 안에서 실행한다.

- 서비스 주소는 compose 서비스 이름이다. 예: `http://<서비스>:<포트>`
- 검사 컨테이너는 서비스에만 접속할 수 있고, 바깥(인터넷·운영 서비스)과 Docker 소켓에는 닿지 않는다.
- 검사 컨테이너 옵션은 `isolation.hardening_args()`를 따른다: 읽기 전용 루트, `nobody`(65534) 사용자, 권한 제거, 메모리·CPU·프로세스 수 제한.
- 네트워크가 끊겨 있으므로 이미지는 실행기가 검사 전에 받아 둔다.

### 내장 검사

- `wetrun/steps/<이름>.py`를 `python -m wetrun.steps.<이름>`으로 실행한다.
- 실행기가 `wetrun` 소스를 읽기 전용으로 마운트해 쓰므로, 내장 검사는 **표준 라이브러리만** 쓴다.
- 기본 이미지는 `python:3.12-slim`이다.

### 사용자 정의 검사

`use: script`로 사용자가 지정한 이미지와 명령을 실행한다. 아래 입출력 규칙은 같다.

## 2. 입력과 출력

| 경로 (컨테이너 안) | 방향 | 내용 |
|---|---|---|
| `/wetrun/step.json` | 실행기 → 검사, 읽기 전용 | 이 단계의 YAML 설정. `env:` 참조는 실제 값으로 바뀌어 들어간다 |
| `/wetrun/refs.json` | 실행기 → 검사, 읽기 전용 | 기준 데이터 (YAML의 `refs`) |
| `/wetrun/out/result.json` | 검사 → 실행기 | `{"status": "...", "message": "...", "evidence": {...}}` |

| 검사 종료 코드 | 상태 |
|---|---|
| `0` | `pass` |
| `1` | `fail`: 복구가 잘못됨 (예: 해시 불일치, 로그인 거부) |
| 그 외, `result.json` 없음, 시간 초과 | `error`: 검사를 끝까지 하지 못함 |

- `evidence`에는 판단 근거를 담는다. 예: 기대 해시와 실제 해시, HTTP 상태 코드.
- 비밀 값은 `evidence`와 `message`에 넣지 않는다.
- 실행기는 넘겨준 비밀 값이 결과에 섞여 있으면 `***`로 가린다.

## 3. 워크플로 YAML

예시: Immich 템플릿의 모양 (`profiles/immich/workflow.yaml`는 검사 담당이 작성).

```yaml
version: 1
repository:
  path: /backup/restic-repo          # restic 저장소 (로컬 경로 또는 restic URL)
  password: env:RESTIC_PASSWORD       # 비밀 값은 env:<변수>로만 참조한다
snapshot: {tag: immich, select: latest}
compose:
  files: [docker-compose.yml]         # 백업 시점의 compose (워크플로 파일 기준 상대 경로)
  env_file: .env
  env:                                # {restore}는 스냅샷을 복원한 실행 디렉터리 안의 경로
    UPLOAD_LOCATION: "{restore}/data/library"
    DB_DATA_LOCATION: "{run}/postgres"
refs: refs.json
steps:
  - {use: restore}                                    # 스냅샷 복원
  - {use: up, services: [database]}                   # DB만 먼저 기동
  - use: exec                                         # 서비스 컨테이너 안에서 명령 실행
    service: database
    command: [psql, -U, postgres, -d, immich]
    stdin: "{restore}/data/backup/immich.sql"
  - {use: up}                                         # 나머지 기동, healthy 대기
  - {use: http, name: ready, url: "http://immich-server:2283/api/server/ping", timeout: 120}
  - use: ref_files
    name: download-hash
    url: http://immich-server:2283
    account: {email: teamh@wetrun.test, password: env:IMMICH_TEST_PASSWORD}
  - {use: script, name: custom, image: example/check:1, command: [/check.sh], required: false}
```

### 단계 공통 키

| 키 | 기본값 | 뜻 |
|---|---|---|
| `use` | (필수) | 단계 종류 |
| `name` | `use`와 같음 | 리포트에 보일 이름. 워크플로 안에서 겹치지 않아야 한다 |
| `timeout` | 300 | 초. 넘으면 `error` |
| `required` | `true` | `false`면 실패해도 전체 판정에 영향 없음 (기록만) |

### 단계 종류와 담당

| `use` | 담당 | 하는 일 |
|---|---|---|
| `restore` | 실행기 | 스냅샷을 실행 디렉터리에 복원 |
| `up` | 실행기 | 격리 compose 기동, healthy 대기. `services`로 일부만 기동 가능 |
| `exec` | 실행기 | 서비스 컨테이너 안에서 명령 실행 (DB 덤프 복원 등) |
| `http`, `db_query`, `ref_files` | 검사 | 내장 검사 |
| `script` | 검사 (실행은 실행기) | 사용자 정의 검사 컨테이너 |

서비스 고유 내용(SQL, API 경로, 복원 명령)은 YAML에만 쓴다. `wetrun/`은 서비스를 모른다.

### 실행 전 검사 (`wetrun check-input`)

다음 경우 아무것도 띄우지 않고 종료 코드 `2`로 멈춘다.

- 모르는 키나 `use`가 있음
- 필수 키가 없음
- `env:` 변수가 비어 있음
- 파일이 없음
- 같은 `name`이 두 번 나옴

## 4. 실행과 판정 규칙

1. 단계는 YAML 순서대로 실행한다.
2. 필수 단계가 `pass`가 아니면 남은 단계는 모두 `skipped`로 기록하고 실행하지 않는다.
3. 전체 판정: 필수 단계가 **모두** `pass`일 때만 `pass`다.
   - 필수 단계가 하나도 없음 → `error`
   - 건너뛴 필수 단계가 남음 → `error`
4. 정리(이번 실행의 컨테이너·네트워크·볼륨·실행 디렉터리 삭제)는 YAML에 쓰지 않는다. 성공·실패·시간 초과·중단 모두에서 항상 한다.

### CLI 종료 코드

| 코드 | 뜻 |
|---|---|
| `0` | 통과 |
| `1` | 복구 검증 실패 (`fail`) |
| `2` | 입력·실행 조건 오류 (`error`) |
| `3` | 정리 실패. 판정보다 우선한다 (남은 자원을 운영자가 치워야 함) |

## 5. 실행 결과 → 리포트

실행기는 `contract.RunResult`를 `report.py`에 넘긴다.

- 담는 내용: 실행 ID, 스냅샷 ID, 워크플로 해시, 이미지 digest, 단계별 `StepResult`, 정리 오류, 소요 시간
- 리포트의 JSON·요약 형식은 검사·출력 담당이 정한다.
