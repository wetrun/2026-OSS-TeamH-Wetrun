# Wetrun 사용 안내

Wetrun은 기존 restic 백업으로 Docker Compose 서비스를 **운영과 분리된 곳에 실제로 다시 띄우고**, 로그인·조회·다운로드 같은 사용자 동작으로 쓸 수 있는지 확인한다. 백업을 만들지 않고, 운영 서비스를 건드리지 않는다.

v0.1은 Immich를 지원한다 ([`profiles/immich/workflow.yaml`](../profiles/immich/workflow.yaml)).

## 1. 준비

| 필요한 것 | 버전 | 확인 |
|---|---|---|
| Linux | Ubuntu 26.04 기기와 GitHub CI의 ubuntu 러너에서 확인 | |
| Docker, Compose v2 | Docker 29, Compose 2.40 이상에서 확인 | `docker compose version` |
| restic | **0.18 이상** (apt 버전은 오래됐다. [릴리스](https://github.com/restic/restic/releases)에서 받는다) | `restic version` |
| uv, Python 3.12 | | `uv --version` |

```sh
git clone https://github.com/wetrun/2026-OSS-TeamH-Wetrun.git wetrun && cd wetrun
make install
```

**자원.** 검증하는 동안 서비스가 하나 더 뜬다.
- 메모리: 서비스 하나만큼 더 필요하다. Immich는 ML을 빼고 약 1.2GB를 쓴다.
- 디스크: 복원할 백업 크기만큼 필요하다. 부족하면 시작 전에 멈춘다.
- 운영 서버가 빠듯하면 restic 저장소에 접근할 수 있는 **다른 컴퓨터**에서 돌린다. 실제 재해 때도 다른 컴퓨터로 복구하므로 더 현실적인 시험이 된다.

**오프라인.** 검증 네트워크는 바깥과 끊긴다. 서비스 이미지와 `python:3.12-slim`(검사용), `alpine:3`(확인·정리용)을 미리 받아 둔다.

## 2. 워크플로 작성

워크플로 YAML 하나가 "어느 백업을, 어떻게 띄우고, 무엇을 확인할지"를 정한다. Immich 프로필을 복사해서 경로만 바꾸는 것이 가장 쉽다.

```yaml
version: 1
repository:
  path: /backup/restic-repo            # restic 저장소 (로컬 경로 또는 sftp:, s3: 같은 URL)
  password: env:RESTIC_PASSWORD         # 비밀 값은 env:<변수>로만 쓴다
snapshot: {tag: immich, select: latest} # 이 태그의 가장 최근 스냅샷
compose:
  files: [/srv/immich/docker-compose.yml]   # 운영과 같은 compose 파일
  env_file: /srv/immich/.env
  env:
    UPLOAD_LOCATION: "{restore}/data/library"   # {restore}: 백업을 푼 곳
    DB_DATA_LOCATION: "{run}/postgres"          # {run}: 이번 실행의 임시 폴더
refs: /srv/wetrun/refs.json             # 정답지: 사진별 SHA-1 등. 백업 밖에 둔다
steps: ...                              # profiles/immich/workflow.yaml 참고
```

- 상대 경로는 워크플로 파일 위치 기준이다.
- 운영 compose를 그대로 쓰지만, Wetrun이 이름·포트·네트워크를 바꿔서 띄운다. 운영 볼륨, 외부 네트워크, Docker 소켓, 실행 폴더 밖 마운트가 있으면 **실행을 거부한다**. 예외는 `/etc/localtime`과 `/etc/timezone`의 읽기 전용 마운트뿐이다.
- 단계와 키의 자세한 규칙은 [contract.md](contract.md) 3절에 있다.

**정답지(`refs.json`).** 사진이 실제로 맞는지는 원본을 내려받아 정답지의 해시와 대조해서 확인한다. testenv에서는 `make seed`가 만든다(`testenv/seed.py`). 운영 서비스용 정답지는 `wetrun refs`로 만들어 백업 밖에 둔다.

```sh
export TESTENV_ADMIN_PASSWORD=...   # ref_files 단계가 env:로 참조하는 값
uv run wetrun refs workflow.yaml --url http://localhost:2283   # 운영 서비스 주소
```

- 워크플로의 `ref_files` 단계 설정(로그인·목록·다운로드 경로)으로 운영 서비스에 로그인해, 원본을 모두 받아 SHA-1을 계산하고 워크플로의 `refs` 경로에 쓴다(`-o`로 바꿀 수 있다). 운영 서비스에는 읽기 요청만 보낸다.
- `--url`이 필요한 이유: 워크플로의 `url`은 검증 환경 안의 주소(`http://immich-server:2283`)라서 운영 서비스를 가리키지 않는다.
- 원본이 서비스 기록과 다르거나 받지 못한 파일은 넣지 않고 이름을 알려 준다. 운영 데이터가 이미 망가진 것일 수 있으니 먼저 확인한다.
- 이미 있는 정답지는 덮어쓰지 않는다. 기준 사진을 일부러 지우거나 바꾼 뒤에는 `--force`로 다시 만든다. 그러지 않으면 멀쩡한 백업도 `fail`이 난다. 사진을 새로 추가한 것은 `fail`이 아니므로 다시 만들 필요가 없다.
- 운영 데이터가 망가진 상태에서 만들면 그 상태가 정답이 된다. 원본이 서비스 기록과 다른 파일은 빼 주지만, 기록까지 함께 망가진 것은 알 수 없다.

**백업할 때마다 자동으로 만들기.** 백업 스크립트에서 `restic backup` **바로 앞에** 한 줄 넣으면 정답지를 따로 관리할 필요가 없다.

```sh
# 백업 스크립트 (예: 매일 03:00). 정답지를 만들지 못해도 백업은 한다
wetrun refs /etc/wetrun/workflow.yaml --url http://localhost:2283 --force \
  || echo "wetrun refs 실패: 지난 정답지로 검증한다" >&2
restic backup /srv/immich ...
```

- **백업 앞에 두는 이유:** 정답지를 만든 뒤 백업 전에 올라온 사진은 백업에만 있으므로 실패가 아니다(기준보다 파일이 많은 것은 실패가 아니다). 반대로 백업 뒤에 만들면 그 사이에 올라온 사진이 정답지에만 있어 멀쩡한 백업이 `fail`이 난다. 휴대폰 자동 업로드가 있으면 자주 일어난다.
- 정답지를 만든 뒤 백업 전에 기준 사진을 지우면 `fail`이 날 수 있다. 그 사이가 짧으므로 드물다.
- 원본을 모두 받으므로 사진이 많으면 시간이 걸린다(로컬 측정에서 약 0.2GiB/s). `--timeout`(기본 3600초)을 넘으면 정답지를 바꾸지 않고 끝난다.
- cron에서 돌릴 때는 `ref_files` 단계가 `env:`로 참조하는 비밀번호를 백업 스크립트 환경에 넣어 둔다.

### 다른 서비스에 쓸 때

Immich 말고도 Gitea(SQLite)와 Nextcloud(MariaDB)로 확인했다. 워크플로 예시는 [eval/services/](../eval/services/README.md)에 있다.

- **compose가 데이터 경로를 `./data`처럼 직접 적는다면** `compose.project_dir: "{restore}"`를 쓴다. 안 쓰면 빈 폴더가 붙어서, 멀쩡한 백업이 `fail`로 나온다.
- **데이터를 이름 있는 볼륨에 둔다면**(compose의 `volumes:` 아래 이름이 선언된 방식) `compose.volumes: {<볼륨 이름>: "{restore}/<백업 안 경로>"}`를 쓴다. 안 쓰면 빈 볼륨이 붙어서, 멀쩡한 백업이 `fail`로 나온다.
- **복원 후 할 일**(파일 소유자 되돌리기, 유지보수 모드 해제 등)은 `exec` 단계로 넣는다.
- **접속 주소(Host)를 검사하는 서비스**(Nextcloud 등)는 `http` 검사에 `headers: {Host: localhost}`처럼 허용된 주소를 넣는다. 안 넣으면 HTTP 400으로 `fail`이 난다.
- **API가 파일 체크섬을 주지 않으면** `script` 검사를 쓴다. 이때 서비스가 응답하지 않는 경우(시간 초과)는 `fail`로 끝내야 한다. `error`로 끝내면 고장 난 백업을 놓친다.
- 새 워크플로는 **정상 백업으로 먼저 `pass`가 나오는지** 확인한다. 설정이 틀려도 `fail`이 나올 수 있다.

## 3. 실행

```sh
export RESTIC_PASSWORD=...        # 워크플로가 env:로 참조하는 값을 모두 넣는다
uv run wetrun check-input workflow.yaml   # 아무것도 띄우지 않고 입력만 검사
uv run wetrun run workflow.yaml
```

터미널에서 실행하면 단계마다 진행 상황이 나온다. 실행 중인 단계는 회색 한 줄(`[3/6] restore-db   명령 실행 중... 12초`)로 갱신되다가, 끝나면 판정(pass 초록, fail 빨강, error 노랑)·걸린 시간·메시지로 바뀐다. 끝난 줄이 단계 표가 되므로 마지막 요약에는 결과와 할 일만 나온다. 색을 끄려면 `NO_COLOR=1`.

```
[1/6] restore      pass     6.9초  스냅샷 복원
...
[6/6] photos       pass     3.2초  파일 5개 전부 확인, 모두 원본과 일치
정리 완료 0.8초

Wetrun 결과: PASS (종료 코드 0)
실행 20261124-132041-dc60dd · 스냅샷 bff850f9 (1시간 안) · 104.4초
리포트: /home/me/.local/share/wetrun/runs/20261124-132041-dc60dd.json
```

cron 로그나 파일로 받을 때는 진행 표시 없이 끝난 뒤 요약만, 단계 표를 포함해 나온다. 출력 예:

```
Wetrun 결과: FAIL (종료 코드 1)
할 일: 백업 데이터 점검. photos 단계와 JSON 리포트 확인
실행 20261114-120508-00a0b7 · 스냅샷 8d0806b7 · 53.2초

  pass     restore        2.2초  스냅샷 복원
  pass     restore-db    12.3초  명령 성공
  pass     up            31.0초  서비스 기동
  pass     ready          0.4초  200 응답 (1번째 시도)
  fail     photos         0.6초  원본 다운로드 실패 (HTTP 404)
리포트: /home/me/.local/share/wetrun/runs/20261114-120508-00a0b7.json
```

## 4. 결과 읽기

| 종료 코드 | 판정 | 뜻 | 할 일 |
|---|---|---|---|
| `0` | `pass` | 이 백업으로 복구할 수 있다 | 없음 |
| `1` | `fail` | **백업이나 복구한 데이터에 문제가 있다** (덤프 손상, 사진 누락 등) | 백업을 확인한다 |
| `2` | `error` | 검증을 끝내지 못했다. 백업이 망가졌다는 뜻은 아니다 (비밀번호 틀림, 디스크·메모리 부족 등) | 환경·설정을 고친다 |
| `3` | | 정리에 실패했다. 판정보다 우선한다 | 리포트의 정리 오류를 보고 남은 자원을 지운다 |

- 단계별 근거(종료 코드, 오류 메시지, 기대 해시와 실제 해시)는 JSON 리포트에 있다.
- 리포트는 `~/.local/share/wetrun/runs/<실행 ID>.json`에 쌓인다 (`WETRUN_REPORT_DIR`로 변경). 본인만 읽을 수 있게(0600) 저장된다.
- 비밀 값은 출력과 리포트에서 `***`로 가린다.
- 성공·실패·중단(Ctrl+C) 어느 경우에도 이번 실행이 만든 컨테이너·네트워크·볼륨·폴더만 지운다.

## 5. 매일 자동으로 돌리기

```sh
# 비밀 값 파일 (본인만 읽게)
umask 077
cat > ~/.config/wetrun.env <<'EOF'
RESTIC_PASSWORD=...
IMMICH_ADMIN_PASSWORD=...        # account.password가 env:로 참조하는 변수
WETRUN_DISCORD_WEBHOOK=https://discord.com/api/webhooks/...
EOF

uv run wetrun schedule workflow.yaml --at 03:30 --env-file ~/.config/wetrun.env
```

출력되는 한 줄을 `crontab -e`로 붙여 넣는다.
- 그 줄에 PATH, 비밀 값 파일, 로그 위치(`~/.local/share/wetrun/cron.log`)가 들어 있다.
- 같은 워크플로가 이미 돌고 있으면 새 실행은 종료 코드 `2`로 멈춘다.
- 검증 중에는 자원을 더 쓰므로 사용량이 적은 시간대로 잡는다.

## 6. 실패 알림 (Discord)

워크플로에 추가한다. 웹훅 주소는 비밀 값이라 `env:`로만 쓸 수 있다.

```yaml
notify:
  discord: env:WETRUN_DISCORD_WEBHOOK
  when: [fail, error]     # 기본값. 매번 받으려면 [pass, fail, error]
```

- `on:` 대신 `when:`을 쓴다. YAML은 `on`을 true로 읽는다.
- 알림이 실패해도 판정은 바뀌지 않는다.

### 알림이 없다고 정상이라는 뜻은 아니다

Wetrun이 보장하는 것은 **실행되면 결과를 남기고, 실패하면 알린다**까지다. 예약 실행이 **아예 돌지 않으면** 아무 연락도 오지 않는다. 예를 들면 다음과 같은 경우다.

- 서버가 꺼졌거나 재부팅 뒤 cron이 돌지 않음
- crontab이 지워짐
- 디스크가 가득 차서 시작하지 못함

멈춘 프로그램은 스스로 멈췄다고 알릴 수 없다. 그래서 이 경우를 잡으려면 **서버와 독립된 관찰자**가 있어야 한다. Wetrun은 같은 서버 안에서 이를 흉내 내지 않는다. 서버가 멈출 때 같이 멈추는 장치는 "멈춤도 잡아 준다"는 잘못된 믿음만 주기 때문이다.

필요하면 아래 중 하나로 관찰자를 둔다.

| 관찰자 | 방법 |
|---|---|
| 사람 | `when: [pass, fail, error]`로 매일 결과를 받는다. **메시지가 오지 않은 날이 문제가 생긴 날**이다 |
| 내가 가진 다른 컴퓨터 | 그 컴퓨터의 cron이 서버의 마지막 리포트 시각을 확인하고, 오래됐으면 알린다. 아래 예시 |
| 감시 서비스 | healthchecks.io 같은 서비스나, 다른 컴퓨터에 직접 띄운 Uptime Kuma. crontab 줄 끝에 `; curl -fsS -m 10 <감시 주소>`를 붙인다 |

다른 컴퓨터에서 확인하는 예시다. 서버의 리포트가 36시간 넘게 없으면 실패한다.

```sh
# 다른 컴퓨터의 crontab. 서버에 ssh 키로 접속할 수 있어야 한다
0 9 * * * ssh 서버 'find ~/.local/share/wetrun/runs -name "*.json" -mmin -2160 | grep -q .' || echo "Wetrun 리포트가 36시간 넘게 없음" | mail -s "Wetrun 멈춤" 나
```

## 7. 원격 저장소의 백업 검증하기

실제 재해(디스크 고장 등)가 나면 같은 서버의 백업도 같이 사라진다. 그래서 **다른 곳에 둔 백업을 검증하는 쪽이 더 의미 있다.** Wetrun은 restic이 지원하는 저장소를 그대로 쓴다.

```yaml
repository:
  path: sftp:backup-server:/srv/restic-repo   # 또는 env:WETRUN_REPO (접속 정보가 든 주소)
  # path: s3:https://s3.example.com/bucket/repo  (키는 AWS_ACCESS_KEY_ID·AWS_SECRET_ACCESS_KEY 환경 변수)
  # path: env:WETRUN_REPO  →  WETRUN_REPO=rest:https://user:pass@backup.example.com/repo/
  password: env:RESTIC_PASSWORD
  read_only: true                               # 검증 계정이 읽기 권한만 있을 때
```

보안을 위해 다음을 권한다.

| 항목 | 권장 | 이유 |
|---|---|---|
| 검증 계정 권한 | **읽기 전용** + `read_only: true` | 검증 컴퓨터가 뚫려도 그 계정으로 백업을 지울 수 없다. 랜섬웨어는 백업부터 지운다. S3는 읽기·목록 권한만 준 키, REST 서버는 `--append-only` 모드나 읽기 전용 사용자 |
| 저장소 주소 | 접속 정보가 들어가면 `env:`로 | YAML이 커밋되면 공개된다 |
| ssh 키 | 검증 전용 키. 서버의 `authorized_keys`에 `restrict` 옵션을 붙이고 sftp만 허용 | cron에서 쓰려면 비밀번호 없는 키가 필요하니, 키가 할 수 있는 일을 줄인다 |
| 호스트 키 | 처음에 한 번 직접 `ssh`로 접속해 `known_hosts`에 등록 | Wetrun은 호스트 키 확인을 끄지 않는다. 모르는 서버면 묻지 않고 실패한다 |
| 검증 컴퓨터 | 운영 서버만큼 믿을 수 있는 곳 | 검증하는 동안 복원한 사진과 DB가 실행 디렉터리(본인만 접근, 0700)에 평문으로 풀린다. 끝나면 지운다 |

- 백업 내용은 restic이 저장하기 전에 암호화하므로, 저장소를 두는 서버나 클라우드는 내용을 볼 수 없다. 전송 구간도 sftp(ssh)가 암호화한다.
- 원격 저장소는 복원이 느려진다(시험에서 로컬 3초 → sftp 14초). 클라우드는 내려받기 요금이 붙을 수 있다. `restore`의 `timeout`을 넉넉히 두거나 실행 이력의 자동 조정에 맡긴다.
- Discord 알림에는 단계 메시지(실패한 파일 이름 등)가 들어간다. 파일 이름도 외부로 나가면 안 되는 환경이면 알림을 쓰지 않는다.

## 8. 자주 겪는 문제

| 증상 | 원인·해결 |
|---|---|
| `restore` 단계 `error`: 비밀번호가 틀림 / 저장소가 없음 | `RESTIC_PASSWORD`, `repository.path` 확인 |
| `restore` 단계 `fail`: 스냅샷이 없음 | 그 태그로 만든 백업이 없다. 태그가 맞는지, 백업이 실제로 돌고 있는지 확인 |
| 디스크 공간 부족 (`error`) | `WETRUN_WORKDIR`를 공간이 넉넉한 곳으로 (기본 `/var/tmp/wetrun`) |
| 메모리 부족으로 서비스가 종료됨 (`error`) | 다른 컨테이너를 끄거나, 다른 컴퓨터에서 돌리거나, 검증에 필요 없는 서비스를 `up`의 `services`에서 뺀다. 서비스별 상한은 `compose.mem_limit`(기본 2g) |
| 격리 규칙 위반 (`error`) | compose에 운영 볼륨·외부 네트워크·Docker 소켓·실행 폴더 밖 마운트, 호스트 경로에 붙는 볼륨(`driver_opts`), `cap_add`·`privileged` 같은 권한 설정이 있다. 메시지에 나온 항목을 검증용 compose에서 빼거나, 그 서비스를 `up`의 `services`에서 뺀다 |
| "남이 쓸 수 있는 폴더라 쓰지 않음" / "다른 사용자 소유 폴더" | 여러 사람이 쓰는 서버에서 비밀 값이 든 파일을 남이 가로채지 못하게 막은 것이다. 메시지의 폴더를 `chmod go-w`로 바꾸거나, `WETRUN_WORKDIR`를 본인 홈 아래로 지정한다 |
| `restore-db` 단계 `fail`: psql 종료 코드 3 | DB 덤프가 깨졌다. `pg_dumpall --clean` 덤프는 프로필의 복원 명령처럼 접속 사용자 삭제·생성 두 줄을 걸러야 한다 |
| 같은 워크플로가 이미 실행 중 | 앞 실행이 끝나기를 기다린다. 예약 시간이 겹치지 않는지 확인 |
| `restic`이 `$HOME is not defined` | cron이 아닌 곳에서 돌릴 때 `HOME`을 설정한다 |
| `restore` `error`: 잠금 파일을 만들지 못함 (permission denied) | 읽기 전용 저장소다. `repository.read_only: true` |
| `restore` `error`: Permission denied (publickey) / Host key verification failed | ssh 키나 `known_hosts` 설정. 같은 사용자로 `ssh 서버`가 비밀번호 없이 되는지 확인 |
| `restore` `error`: 시간 초과 | 원격 저장소가 응답하지 않거나, **S3 키가 틀렸다**(restic은 S3 인증 실패도 계속 재시도해서 시간 제한까지 기다린다). 네트워크·서버·키(`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`)를 확인한다 |
| `restore` `error`: `PutObject: Access Denied` (S3) | 읽기 전용 키다. `repository.read_only: true` |
| (macOS) Docker가 실행 디렉터리를 볼 수 없음 | `export WETRUN_WORKDIR=~/.cache/wetrun`. macOS의 Docker는 홈 폴더 밖을 빈 폴더로 마운트한다 |

## 9. 한계 (v0.1)

- 지원 서비스는 Immich, 백업 도구는 restic뿐이다.
- 일반 사용자로 복원하면 파일 소유자가 복원한 사용자로 바뀐다. DB 데이터 폴더를 그대로 백업하는 서비스는 root로 실행해야 할 수 있다 (Immich는 덤프로 복원해서 괜찮다).
- 사진이 아주 많으면 정해진 시간 안에서 일부만 내려받아 확인한다. 확인한 수와 놓칠 수 있는 손상 비율은 리포트에 남는다.
- 예약 실행이 아예 돌지 않은 경우는 알리지 못한다 (6절).
- 원격 저장소는 sftp, S3 호환(SeaweedFS), restic REST 서버로 시험했다. AWS S3·Backblaze B2 같은 실제 클라우드는 같은 S3 방식이지만 직접 확인하지 않았다.
