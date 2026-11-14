# handoff: 환경·성능·사용자 평가·문서 (정순준)

담당: `testenv/`, `eval/`(성능·사용자 평가), 사용자 문서

testenv 사용 안내: [testenv/README.md](../../testenv/README.md) (도구, 명령, seed·backup이 만드는 것, 자주 겪는 문제).

## 현재 상태 (2026-11-14)

| 부분 | 파일 | 상태 |
|---|---|---|
| Immich 실행·정리 (`make env-up`, `env-down`, `env-clean`) | `testenv/up.sh`, `down.sh`, `common.sh` | 완료 (#6) |
| 테스트 계정·샘플 사진·앨범, 정답지 `refs.json` (`make seed`) | `testenv/seed.py` | 완료 (#7) |
| DB 덤프와 restic 백업, 한 줄 준비 (`make env`) | `testenv/backup.sh`, `Makefile` | 완료 (#8). 완료 기준 "새로 clone해서 명령 한 줄로 같은 Immich + 백업 상태" 달성 |
| 포트 `127.0.0.1` 한정, 공식 compose의 `container_name` 제거 | `testenv/up.sh`, `.env.example` | 완료 (#9) |
| 대용량 평가 데이터셋 | `testenv/dataset/` | 시작 전 |
| 성능·사용자 평가 | `eval/` | 시작 전 |

## 실행 방법

저장소 루트에서 실행한다.

```sh
make env          # env-up → seed → backup
make env-down     # 멈추기 (데이터는 남음)
make env-clean    # data/까지 삭제 ([y/N] 확인, 스크립트에서는 YES=1)
```

- **접속:** http://localhost:2283, `teamh@wetrun.test` / `testpwd`. 포트는 이 컴퓨터에서만 열린다.
- **Wetrun으로 검증:** `profiles/immich/workflow.yaml`이 testenv 파일을 가리킨다. `export RESTIC_PASSWORD=resticpwd TESTENV_ADMIN_PASSWORD=testpwd` 후 `uv run wetrun run profiles/immich/workflow.yaml`.
- **고장 백업:** testenv 저장소를 복사한 사본에 태그를 달리해 만든다. 원본은 정상 백업 기준으로 둔다 ([test.md](test.md)).

## 확인한 환경

| 환경 | 결과 |
|---|---|
| WSL2 Ubuntu + Docker Desktop | `make env` 성공. 컨테이너 이름 `wetrun-testenv-*-1`, 포트 `127.0.0.1:2283`만, seed·backup·`restic check` 통과 (#9) |
| macOS + Colima | `make env` 문제없음 (bash 3.2, BSD sed). 이 백업으로 Wetrun을 끝까지 돌림 ([runner.md](runner.md)) |
| Ubuntu 26.04 실제 기기 | 이 백업으로 v0.1 목표 확인. 정상 `pass`, 고장 4종 `fail` (design-decisions 11절) |

testenv Immich를 켜 둔 채로 Wetrun을 돌려도 충돌하지 않았다. 실행기가 프로젝트 이름·포트·네트워크를 바꿔 띄우기 때문이다.

## 정한 것과 근거

실행기·검사·테스트가 이 값에 기대므로 바꿀 때는 팀과 먼저 합의한다.

| 결정 | 근거 |
|---|---|
| Immich `v3.3.5` 고정 (`IMMICH_VERSION`) | 누가 만들어도 같은 환경 |
| Compose 프로젝트 이름 `wetrun-testenv` | 공식 compose의 `name: immich` 대신. 같은 컴퓨터의 다른 Immich를 건드리지 않게 (#6) |
| 공식 compose의 `container_name` 삭제 → `wetrun-testenv-<서비스>-1` | 이름이 고정되면 한 컴퓨터에 Immich를 하나만 띄울 수 있다 (#9) |
| 포트 `127.0.0.1:2283` (`TESTENV_BIND_ADDR`) | 공식 compose의 `'2283:2283'`은 `0.0.0.0`과 `[::]`에 열린다. 테스트 비밀번호가 공개돼 있다 (#9) |
| 데이터는 `testenv/data/` 아래 (`library/`, `postgres/`, `backup/`, `restic-repo/`) | 생성물을 한 폴더에 모아 `env-clean`이 그 폴더만 지운다. `.gitignore` 대상 |
| 샘플 사진은 `seed.py`가 직접 그린 무압축 PNG 5장, 앨범 `testenv-album`에 앞 3장 | 다운로드·라이선스 없음. 누가 만들어도 같은 바이트라 SHA-1이 같다. 앨범은 검사의 사진 수 확인용 (#7) |
| DB는 `pg_dumpall --clean --if-exists`로 덤프해서 백업 | 실행 중인 DB 파일을 그대로 복사하면 일관성이 깨질 수 있다 (#8) |
| restic 0.18 이상, 비밀번호 `resticpwd`, 태그·호스트 `testenv` | 실행기 판정이 0.17 이상의 종료 코드에 기댄다. 태그·호스트를 고정해 누가 만들어도 같게 (#8) |
| 정답지 `refs.json`은 `data/` 밖, 백업 밖 | 백업과 같이 망가지면 비교할 기준이 없다 (#7) |
| 스크립트 출력은 영어, 주석·README는 한국어 | 리뷰에서 정한 규칙 (#6~#8) |

## 알려진 한계

- **data/ 권한:** Docker가 bind mount 폴더를 먼저 만들면 root 소유가 된다. `up.sh`가 하위 폴더를 먼저 만들어 막는다. `data/postgres`는 Postgres 사용자(uid 999) 소유라 `chown -R` 하면 Postgres가 켜지지 않는다. 지울 때는 busybox 컨테이너로 지운다.
- **첫 기동:** 처음 `make env-up`의 healthy 대기는 30초~2분이 정상이다. DB 초기화가 늦으면 서버가 잠시 unhealthy로 잡힐 수 있다.
- **seed 직후 백업:** Immich 작업 대기열(썸네일 등)이 끝나기 전에 백업될 수 있다. 아직 기다리는 처리를 넣지 않았다.
- **`.env` 줄 끝:** Windows 편집기로 저장하면 `\r`이 붙어 값이 깨진다. 스크립트가 자동으로 지운다.
- **restic 복원 경로:** 상대 경로로 백업해서 `--target` 아래 `data/...`로 풀린다.
- **백업에 `.env`가 없다.** 그래서 필수 설정 누락 고장은 백업을 고쳐서 만들 수 없다 ([test.md](test.md) 주의).
- **데이터가 작다.** PNG 5장이라 사진이 많을 때의 복원·다운로드 시간은 재지 않았다.

## 다음 작업

1. 필수 설정 누락 고장 시험: 워크플로의 `env_file`에서 값을 빼서 돌리고 결과를 [test.md](test.md)에 반영
2. seed 후 Immich 작업 대기열(`GET /api/queues`)이 빌 때까지 기다리기
3. `refs.json`에 대응 스냅샷 ID 기록 (필드 형식은 검사 담당과 합의). `env-clean`이 `refs.json`을 지우지 않는 점도 같이 정리
4. 대용량 데이터셋(`testenv/dataset/`)과 `eval/` 평가: 사진 수를 늘렸을 때 복원·검사 시간과 `ref_files`의 확인 비율. 기준값은 design-decisions 6·8·14절. 테스트 담당 평가와 범위를 맞춘다
5. README 구조표의 수동 복구 절차·지원 버전 문서가 따로 필요한지 정한다 (사용 안내는 [user-guide.md](../user-guide.md))
