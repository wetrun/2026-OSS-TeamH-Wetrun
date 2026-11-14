# 실행기·검사 계약

실행기(`wetrun/`)와 검사(`wetrun/steps/`, `profiles/`)가 따로 개발해도 맞물리도록 정한 약속.
코드의 기준은 [`wetrun/contract.py`](../wetrun/contract.py). 바꿀 때는 실행기·검사 담당이 함께 합의한다.

## 1. 검사는 검사 컨테이너 안에서 실행한다

복구한 서비스는 바깥과 끊긴(`internal`) 네트워크에 포트 없이 뜬다. 그래서 호스트에서는 접속할 수 없다.
검사는 실행기가 같은 네트워크에 띄운 **검사 컨테이너** 안에서 실행한다.

- 서비스 주소는 compose 서비스 이름이다. 예: `http://<서비스>:<포트>`
- 검사 컨테이너는 서비스에만 접속할 수 있고, 바깥(인터넷·운영 서비스)과 Docker 소켓에는 닿지 않는다.
- 검사 컨테이너 옵션은 `isolation.hardening_args()`를 따른다: 읽기 전용 루트, 권한 제거, 메모리·CPU·프로세스 수 제한.
- 검사는 실행기와 같은 uid·gid로 실행한다 (`isolation.check_user()`). 그래야 `0600`인 `step.json`을 읽고 `out/`에 쓸 수 있다. 실행기가 root면 `nobody`(65534)로 낮추고 실행기가 파일 소유자를 맞춘다.
- 검사 안의 사용자는 `/etc/passwd`에 없을 수 있다. `HOME`이나 사용자 이름에 기대지 않는다.
- 네트워크가 끊겨 있으므로 이미지는 실행기가 검사 전에 받아 둔다.
- 검사 컨테이너는 compose의 `default` 네트워크(없으면 첫 번째 네트워크)에 붙는다.

### 내장 검사

- `wetrun/steps/<이름>.py`를 `python -m wetrun.steps.<이름>`으로 실행한다.
- 실행기가 `wetrun` 소스를 `/opt/wetrun/wetrun`에 읽기 전용으로 마운트하고 `PYTHONPATH=/opt/wetrun`으로 실행한다. 그래서 내장 검사는 **표준 라이브러리만** 쓴다.
- 기본 이미지는 `python:3.12-slim`이다.
- v0.1 내장 검사는 `http`, `ref_files`다. `db_query`는 보류한다: 표준 라이브러리로는 DB에 접속할 수 없고, `exec`는 검사 입출력 규칙 밖이다. 자산 수·앨범 확인은 `ref_files`가 API로 한다.

### 사용자 정의 검사

`use: script`로 사용자가 지정한 이미지와 명령을 실행한다. 아래 입출력 규칙과 `hardening_args()`(읽기 전용 루트, 권한 제거, 자원 제한)는 내장 검사와 같다.

## 2. 입력과 출력

| 경로 (컨테이너 안) | 방향 | 내용 |
|---|---|---|
| `/wetrun/step.json` | 실행기 → 검사, 읽기 전용 | 이 단계의 YAML 설정. 공통 키(`name`, `timeout`, `required`)도 기본값을 채워 포함한다. `env:` 참조는 실제 값으로 바뀌어 들어간다 |
| `/wetrun/refs.json` | 실행기 → 검사, 읽기 전용 | 기준 데이터 (YAML의 `refs`) |
| `/wetrun/out/result.json` | 검사 → 실행기 | `{"status": "...", "message": "...", "evidence": {...}}` |

| 검사 종료 코드 | `result.json`의 `status` | 상태 |
|---|---|---|
| `0` | `pass` | `pass` |
| `1` | `fail` | `fail`: 복구가 잘못됨 (예: 해시 불일치, 로그인 거부, 마감까지 서비스 응답 없음) |
| 그 외, 또는 종료 코드와 `status`가 맞지 않음, `result.json` 없음, 시간 초과 | | `error`: 검사를 끝까지 하지 못함 |

- 종료 코드와 `status`가 둘 다 맞을 때만 `pass`·`fail`이다. 파이썬은 처리하지 않은 예외로 죽으면 종료 코드 `1`을 내므로, `result.json` 없는 `1`을 `fail`로 보지 않는다.
- 검사는 자기 시작 시각부터 `timeout`초 안에 스스로 끝내고 근거를 `result.json`에 쓴다. 마감까지 서비스가 기대대로 응답하지 않으면 `fail`이다.
  - 요청마다 대기 시간을 남은 시간 이하로 줄여 마지막 요청이 마감을 넘지 않게 한다.
- 실행기는 검사 컨테이너를 띄운 시각부터 `timeout` + 30초(`contract.CHECK_TIMEOUT_GRACE_S`)가 지나면 끊고 `error`로 기록한다. 30초는 컨테이너 기동과 결과 쓰기를 위한 여유다.
- 내장 검사는 예외를 잡아 종료 코드 `2`(`error`)로 끝낸다.

- `evidence`에는 판단 근거를 담는다. 예: 기대 해시와 실제 해시, HTTP 상태 코드.
- 비밀 값은 `evidence`와 `message`에 넣지 않는다.
- 실행기는 넘겨준 비밀 값이 결과에 섞여 있으면 `***`로 가린다.

## 3. 워크플로 YAML

예시: Immich 템플릿의 모양 (`profiles/immich/workflow.yaml`는 검사 담당이 작성).

```yaml
version: 1
repository:
  path: /backup/restic-repo          # restic 저장소 (로컬 경로, restic URL, 또는 env:<변수>)
  password: env:RESTIC_PASSWORD       # 비밀 값은 env:<변수>로만 참조한다
  read_only: false                    # true면 잠금 파일을 쓰지 않는다 (읽기 전용 계정용)
snapshot: {tag: immich, select: latest}
compose:
  files: [docker-compose.yml]         # 백업 시점의 compose (워크플로 파일 기준 상대 경로)
  env_file: .env
  env:                                # {restore}는 스냅샷을 복원한 실행 디렉터리 안의 경로
    UPLOAD_LOCATION: "{restore}/data/library"
    DB_DATA_LOCATION: "{run}/postgres"
  mem_limit: 2g                       # 검증 서비스별 메모리 상한 (기본 2g). 서비스별 매핑도 가능
refs: refs.json                       # 기준 데이터. 백업 밖에 두는 정답지
steps:
  - {use: restore}                                    # 스냅샷 복원
  - {use: up, name: up-db, services: [database]}      # DB만 먼저 기동 (up이 두 번이라 name 필요)
  - use: exec                                         # 서비스 컨테이너 안에서 명령 실행
    service: database
    # pg_dumpall --clean 덤프의 접속 사용자 삭제·생성 줄을 걸러야 ON_ERROR_STOP과 함께 쓸 수 있다 (#13)
    command: [sh, -c, "sed -e '/^DROP ROLE IF EXISTS postgres;$/d' -e '/^CREATE ROLE postgres;$/d' | psql -U postgres -d postgres -v ON_ERROR_STOP=1 -q"]
    stdin: "{restore}/data/backup/immich.sql"
    timeout: 600
  - {use: up, services: [immich-server, redis, database]}  # 검증에 필요한 서비스만 기동 (ML 제외)
  - {use: http, name: ready, url: "http://immich-server:2283/api/server/ping", timeout: 120}
  - use: ref_files
    name: download-hash
    url: http://immich-server:2283
    account: {email: teamh@wetrun.test, password: env:IMMICH_TEST_PASSWORD}
  - {use: script, name: custom, image: example/check:1, command: [/check.sh], required: false}
```

### 원격 저장소

- `repository.path`가 `sftp:`, `s3:`, `rest:`처럼 주소 형식이거나 `env:<변수>`이면 로컬 파일을 확인하지 않는다. 접속 정보가 들어간 주소는 `env:`로 써서 YAML에 남기지 않는다. `env:` 값은 결과에서 가려진다.
- `repository.read_only: true`면 restic에 `--no-lock`을 붙인다. 검증 계정에 읽기 권한만 줘도 확인·복원이 된다.
- 복원 전 확인(스냅샷 목록, 복원 크기)에도 `restore` 단계의 `timeout`을 적용한다. 원격 저장소가 응답하지 않으면 restic은 몇 분 넘게 재시도하기 때문이다. 넘으면 `error`이고 `timed_out`으로 기록한다. 끊을 때 restic이 띄운 ssh 같은 자식 프로세스도 같이 끊는다.
- `sftp:` 저장소는 ssh를 비대화식(`BatchMode=yes`)으로 쓴다. 키가 없거나 호스트 키를 모르면 묻지 않고 바로 `error`로 끝난다.

### 경로와 compose 처리

- 상대 경로(`compose.files`, `env_file`, `refs`, 로컬 `repository.path`, `{restore}`가 아닌 `stdin`)는 워크플로 파일 위치 기준이다.
- `{restore}`, `{run}`으로 시작하는 경로는 복원 후에 생기므로 `check-input`이 확인하지 않는다.
- `env_file`은 실행 디렉터리에 같은 이름으로 복사된다(0600). compose 안의 `env_file: .env` 같은 상대 경로가 실행 디렉터리 기준으로 풀리기 때문이다.
- 격리 변환 규칙은 `isolation.violations()`·`sanitize()`가 기준이다. 실행 디렉터리 밖 bind 마운트는 거부하되, `/etc/localtime`·`/etc/timezone`은 읽기 전용일 때만 허용한다.
- 다음도 거부한다: `driver_opts`나 기본(local)이 아닌 드라이버를 쓰는 이름 있는 볼륨(호스트 경로·NFS에 붙을 수 있음), `cap_add`, 보안 장치를 끄는 `security_opt`(`unconfined`, `label=disable`), `cgroup_parent`, 바깥 컨테이너의 `volumes_from`.
- 실행 디렉터리의 기본 폴더와 잠금 폴더는 본인 소유이고 남이 쓸 수 없어야 한다. 아니면 아무것도 띄우지 않고 `error`로 멈춘다.

### 단계 공통 키

| 키 | 기본값 | 뜻 |
|---|---|---|
| `use` | (필수) | 단계 종류 |
| `name` | `use`와 같음 | 리포트에 보일 이름. 워크플로 안에서 겹치지 않아야 한다 |
| `timeout` | 300 (임시) | 초, 양의 정수. 검사가 서비스를 기다리는 시간. 실행기는 여기에 30초를 더해 끊는다 (2절). 기본값은 느린 환경에서도 거짓 실패가 없도록 넉넉하게 잡는 것이 원칙이며, 측정 후 확정한다 |
| `required` | `true` | `false`면 실패해도 전체 판정에 영향 없음 (기록만) |

### 검사별 키

- 내장 검사의 키는 각 `wetrun/steps/<이름>.py`의 `REQUIRED_KEYS`, `OPTIONAL_KEYS` 상수가 기준이다.
- `check-input`은 공통 키를 뺀 나머지 키를 이 상수와 비교한다.
- 안쪽 키(예: `account.email`)는 검사가 실행할 때 확인한다.

### 단계 종류와 담당

| `use` | 담당 | 하는 일 |
|---|---|---|
| `restore` | 실행기 | 스냅샷을 실행 디렉터리에 복원 |
| `up` | 실행기 | 격리 compose 기동, healthy 대기. `services`로 일부만 기동 가능 |
| `exec` | 실행기 | 서비스 컨테이너 안에서 명령 실행 (DB 덤프 복원 등) |
| `http`, `ref_files` | 검사 | 내장 검사 (`db_query`는 v0.1에서 보류) |
| `script` | 검사 (실행은 실행기) | 사용자 정의 검사 컨테이너 |

서비스 고유 내용(SQL, API 경로, 복원 명령)은 YAML에만 쓴다. `wetrun/`은 서비스를 모른다.

### 실행 전 검사 (`wetrun check-input`)

다음 경우 아무것도 띄우지 않고 종료 코드 `2`로 멈춘다.

- 모르는 키나 `use`가 있음
- 필수 키가 없음
- `env:` 변수가 비어 있음
- 파일이 없음
- 같은 `name`이 두 번 나옴
- `timeout`이 양의 정수가 아님
- 실행기 단계(`restore`, `up`, `exec`)에 `required: false`를 씀

## 4. 실행과 판정 규칙

1. 단계는 YAML 순서대로 실행한다.
2. 필수 단계가 `pass`가 아니면 남은 단계는 모두 `skipped`로 기록하고 실행하지 않는다.
3. 전체 판정: 필수 단계가 **모두** `pass`일 때만 `pass`다.
   - 필수 단계가 하나도 없음 → `error`
   - 건너뛴 필수 단계가 남음 → `error`
4. 정리(이번 실행의 컨테이너·네트워크·볼륨·실행 디렉터리 삭제)는 YAML에 쓰지 않는다. 성공·실패·시간 초과·중단 모두에서 항상 한다.
5. 중단(Ctrl+C·SIGTERM)되면 진행 중이던 단계는 `error`, 나머지는 `skipped`다.

### 실행기 단계 판정 (#13)

원칙: 원인이 백업 내용에 있으면 `fail`, 실행 환경이나 입력에 있으면 `error`.

| 단계 | `fail` | `error` |
|---|---|---|
| `restore` | 복원 전 확인을 통과한 뒤의 복원 실패(저장 데이터 손상), 태그에 맞는 스냅샷 없음 | 저장소 접근 불가, 비밀번호 틀림, 저장소 잠김, 디스크 공간 부족, 시간 초과 |
| `up` | 컨테이너는 만들었지만 정상 상태가 되지 못함 (종료, unhealthy) | 컨테이너를 만들지 못함(이미지 없음 등), compose 해석 실패·격리 규칙 위반, docker가 응답하지 않음 |
| `exec` | 0이 아닌 종료 코드, `{restore}` 안의 입력 파일 없음 | 서비스가 실행 중이 아님, 종료 코드 126·127·137, 시간 초과 |
| 모든 단계 | | 이번 실행의 컨테이너가 메모리 부족으로 죽어서 실패함 (`OOMKilled`) |

- restic은 데이터 손상과 환경 문제를 둘 다 종료 코드 1로 낸다. 그래서 복원 전에 환경 원인을 먼저 확인한다.
- 실행 전에 Docker가 실행 디렉터리를 실제로 볼 수 있는지 확인하고, 못 보면 아무것도 띄우지 않고 `error`(종료 코드 2)로 멈춘다. macOS의 Docker는 공유하지 않은 경로를 빈 폴더로 마운트해서, 정상 백업이 `fail`로 잘못 나올 수 있기 때문이다.
- 실행기 단계 `evidence`: 종료 코드, 비밀 값을 가린 stderr 마지막 20줄, 컨테이너 이름과 상태.

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
- `wetrun run`은 요약을 출력하고 JSON 리포트를 `$WETRUN_REPORT_DIR/<실행 ID>.json`(기본 `~/.local/share/wetrun/runs/`, 0600)에 저장한다.
  저장에 실패해도 판정과 종료 코드는 바뀌지 않는다 (경고만 출력).
- 알림은 최상위 `notify:` 키로 켠다. 알림 실패도 판정을 바꾸지 않는다.

```yaml
notify:
  discord: env:WETRUN_DISCORD_WEBHOOK   # 웹훅 주소는 비밀 값이라 env:로만 쓴다
  when: [fail, error]                   # 기본값. pass·fail·error 중에서. `on`은 YAML이 true로 읽어서 쓰지 않는다
```

- 알림 첫 줄의 서비스 이름은 워크플로 파일에서 정한다: `<서비스>/workflow.yaml`이면 폴더 이름, 아니면 파일 이름.

## 6. 실행 이력 (#37)

리포트 폴더(`$WETRUN_REPORT_DIR`)에 쌓인 리포트가 실행 이력이다. 실행기는 이 이력으로 시간 제한을 정하고, 느려진 단계를 알리고, 시작 전에 메모리 여유를 확인한다. 설계 근거는 [design-decisions.md](design-decisions.md) 4·8절.

### 리포트에 추가하는 값

| 값 | 위치 | 뜻 | 쓰는 곳 |
|---|---|---|---|
| `workflow_id` | `RunResult` | 같은 워크플로를 묶는 값. 워크플로 파일 절대 경로의 SHA-256 앞 16자 | 이력을 워크플로별로 모으기. `workflow_sha256`(내용 해시)은 YAML을 조금만 고쳐도 바뀌어서 쓰지 않는다 |
| `timed_out` | `StepResult` | 실행기가 시간 제한으로 끊었는지 | 끊긴 실행은 실제로 얼마나 걸렸을지 모르므로 표본에서 뺀다 (Karn 규칙). 다음 실행의 시간 제한을 2배로 |
| `memory_peak_bytes` | `RunResult` | 서비스별로 관측한 최대 메모리 (바이트) | 시작 전 메모리 여유 확인 |
| `snapshot_time` | `RunResult` | 검사한 스냅샷의 생성 시각 (ISO 8601) | 백업이 멈춰 옛 스냅샷만 검사하는 경우 알리기 |
| `warnings` | `RunResult` | 판정에 영향 없는 알림 문장 목록 | "평소보다 느림", "검사한 백업이 N일 전 것" 경고를 요약·알림에 보여 주기 |

- 모두 기본값이 있어(`""`, `false`, `{}`, `[]`) 이전 리포트도 그대로 읽힌다. `report_version`은 1을 유지한다.
- `workflow_id`는 `__main__`의 중복 실행 잠금 키와 같은 함수로 만든다.
- 메모리는 `up` 단계와 검사 단계가 끝날 때 `docker stats --no-stream`으로 잰 값 중 최댓값이다. 순간 최대치가 아니라 표본이므로, 쓸 때 여유를 둔다.
- `warnings`에는 비밀 값을 넣지 않는다. 실행기가 다른 결과처럼 가린다.

### 경고 (`warnings`)

판정과 종료 코드는 바꾸지 않는다.

| 경고 | 조건 |
|---|---|
| 검사한 백업이 N일 전 것 | `snapshot_time`이 `snapshot.max_age_days`(기본 3일)보다 오래됨. 백업 작업이 멈추면 Wetrun은 같은 옛 스냅샷을 매일 검사하고 `pass`를 내기 때문이다 |
| 평소보다 느림 | 아래 이력 계산에서 `duration > Est + 4·Dev` |

- 요약에는 "할 일" 아래 "참고:" 줄로 보인다.
- 알림을 보낼지는 `notify.when`만 보고 정한다. **경고만으로는 알림을 보내지 않는다.** "알림이 오면 할 일이 있다"를 지키기 위해서다. 보내는 알림에는 경고를 같이 넣는다. 그래서 `when`에 `pass`를 넣어 매일 결과를 받는 사람은 `pass` 알림에서 경고를 본다.

```yaml
snapshot: {tag: immich, select: latest, max_age_days: 3}   # 백업 주기에 맞춘다
```

### 실행기가 이력을 쓰는 방법

1. 리포트 담당의 `report.load_history(dir, workflow_id, limit=20)`로 같은 `workflow_id`의 리포트를 최근 순으로 읽는다. 읽지 못하는 파일은 건너뛴다.
2. 단계(`name`)별로 `pass`이고 `timed_out`이 아닌 실행의 `duration_s`만 표본으로 쓴다. 표본이 5개 미만이면 쓰지 않는다.
3. 표본으로 평균(`Est`)과 변동폭(`Dev`)을 계산한다 (RFC 6298과 같은 방식).

```
Est ← 0.875·Est + 0.125·duration
Dev ← 0.75·Dev  + 0.25·|duration − Est|
```

| 쓰임 | 대상 | 판정 영향 |
|---|---|---|
| 시간 제한 = `Est + 4·Dev` (하한 60초, 상한 기본값의 2배). 직전 실행이 끊겼으면 2배 | `restore`, `exec` 중 YAML에 `timeout`을 직접 쓰지 않은 단계 | 있음 (끊기는 시점) |
| `duration > Est + 4·Dev`이면 `warnings`에 "평소보다 느림" | 모든 단계 | 없음 (경고) |
| `up` 직전, 띄울 서비스의 `memory_peak_bytes` 합계 × 1.2 > 빈 메모리이면 띄우지 않고 `error` | `up` | 있음 (`error`) |

- 검사와 `up`의 시간 제한은 판정 기준이므로 자동으로 바꾸지 않는다. 늘어나는 시간 제한은 점점 느려지는 문제를 가린다.
- 리포트를 읽지 못하거나 형식이 다르면 이력이 없는 것으로 보고 기본값을 쓴다. 이력 때문에 실행이 실패하지 않는다.
