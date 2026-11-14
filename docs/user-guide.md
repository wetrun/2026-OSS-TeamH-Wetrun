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

**정답지(`refs.json`).** 사진이 실제로 맞는지는 원본을 내려받아 정답지의 해시와 대조해서 확인한다. testenv에서는 `make seed`가 만든다(`testenv/seed.py`). 운영 서비스용 정답지는 백업할 때 함께 만들어 백업 밖에 둔다.

## 3. 실행

```sh
export RESTIC_PASSWORD=...        # 워크플로가 env:로 참조하는 값을 모두 넣는다
uv run wetrun check-input workflow.yaml   # 아무것도 띄우지 않고 입력만 검사
uv run wetrun run workflow.yaml
```

출력 예:

```
Wetrun 결과: FAIL (종료 코드 1)
할 일: 백업이나 복구한 데이터에 문제가 있음. photos 단계를 확인 (근거는 JSON 리포트)
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
- 기본 설정에서는 예약 실행이 아예 돌지 않으면 아무 연락도 오지 않는다. 걱정되면 `when`에 `pass`를 넣어 매일 결과를 받는다.

## 7. 자주 겪는 문제

| 증상 | 원인·해결 |
|---|---|
| `restore` 단계 `error`: 비밀번호가 틀림 / 저장소가 없음 | `RESTIC_PASSWORD`, `repository.path` 확인 |
| `restore` 단계 `fail`: 스냅샷이 없음 | 그 태그로 만든 백업이 없다. 태그가 맞는지, 백업이 실제로 돌고 있는지 확인 |
| 디스크 공간 부족 (`error`) | `WETRUN_WORKDIR`를 공간이 넉넉한 곳으로 (기본 `/var/tmp/wetrun`) |
| 메모리 부족으로 서비스가 종료됨 (`error`) | 다른 컨테이너를 끄거나, 다른 컴퓨터에서 돌리거나, 검증에 필요 없는 서비스를 `up`의 `services`에서 뺀다. 서비스별 상한은 `compose.mem_limit`(기본 2g) |
| 격리 규칙 위반 (`error`) | compose에 운영 볼륨·외부 네트워크·Docker 소켓·실행 폴더 밖 마운트가 있다. 메시지에 나온 항목을 확인한다 |
| `restore-db` 단계 `fail`: psql 종료 코드 3 | DB 덤프가 깨졌다. `pg_dumpall --clean` 덤프는 프로필의 복원 명령처럼 접속 사용자 삭제·생성 두 줄을 걸러야 한다 |
| 같은 워크플로가 이미 실행 중 | 앞 실행이 끝나기를 기다린다. 예약 시간이 겹치지 않는지 확인 |
| `restic`이 `$HOME is not defined` | cron이 아닌 곳에서 돌릴 때 `HOME`을 설정한다 |
| (macOS) Docker가 실행 디렉터리를 볼 수 없음 | `export WETRUN_WORKDIR=~/.cache/wetrun`. macOS의 Docker는 홈 폴더 밖을 빈 폴더로 마운트한다 |

## 8. 한계 (v0.1)

- 지원 서비스는 Immich, 백업 도구는 restic뿐이다.
- 일반 사용자로 복원하면 파일 소유자가 복원한 사용자로 바뀐다. DB 데이터 폴더를 그대로 백업하는 서비스는 root로 실행해야 할 수 있다 (Immich는 덤프로 복원해서 괜찮다).
- 사진이 아주 많으면 정해진 시간 안에서 일부만 내려받아 확인한다. 확인한 수와 놓칠 수 있는 손상 비율은 리포트에 남는다.
