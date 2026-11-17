# handoff: 환경·성능·사용자 평가·문서 (정순준)

담당: `testenv/`, `eval/`(성능·사용자 평가), 사용자 문서

testenv가 준비돼야 실행기·검사 개발이 시작된다. 막히면 바로 공유한다.
testenv 완료 기준: 새로 clone해서 명령 한 줄로 같은 Immich + 백업 상태를 만들 수 있다.

## 현재 상태 (2026-11-17)

| 부분 | 파일 | 상태 |
|---|---|---|
| 시험용 Immich + 백업 | `testenv/`, `make env` | 완료 (#6~#9). WSL2·macOS에서 `make env` 확인 |
| 크기별 측정용 데이터셋 | `testenv/seed_dataset.py`, `make seed-dataset N=...` | 완료 (#52). JPEG·MP4, 압축·중복 제거 안 되는 데이터 |
| 데이터 크기별 성능 평가 | [eval/scale/README.md](../../eval/scale/README.md) | 300/1500/3000개 x 3회 측정, 9회 모두 pass |
| 다른 서비스 범용성 | [eval/services/README.md](../../eval/services/README.md) | Gitea·Nextcloud 시험 (#47, #48, #50) |

## testenv에서 정한 값

자세한 사용법과 문제 해결은 [testenv/README.md](../../testenv/README.md).

| 항목 | 값 |
|---|---|
| Immich 버전 | `IMMICH_VERSION` (현재 v3.3.5). 바꾸려면 팀과 합의 |
| Compose 프로젝트 | `wetrun-testenv` (다른 Immich와 겹치지 않게). 공식 compose의 `container_name`은 `up.sh`가 지운다 |
| 포트 | `127.0.0.1:2283` (`TESTENV_BIND_ADDR`) |
| 데이터 | `testenv/data/` (library, postgres, backup, restic-repo). 커밋하지 않는다 |
| 테스트 계정 | `teamh@wetrun.test` / `testpwd` (시험 전용) |
| 기본 데이터 | `make seed`: 샘플 PNG 5장, 앨범 `testenv-album`(앞 3장), 정답지 `refs.json` |
| 백업 | `make backup`: `pg_dumpall` 덤프 + `data/library/` → restic(비밀번호 `resticpwd`, 태그·호스트 `testenv`). restic 0.18 이상 |

## 크기별 측정용 데이터셋 (`make seed-dataset`)

- `make seed` 뒤에 실행한다. N은 데이터셋 개수다: `N=295 / 1495 / 2995` → 샘플 5장과 합쳐 Immich 전체 300 / 1500 / 3000개
- 사진: 4032x3024 JPEG(장당 약 2.6~5.2MB). 동영상: 50개 중 1개, 1080p H.264 MP4(10~30MB)
- Immich 서버 이미지 안의 ffmpeg로 만든다. 버전이 같으면 누가 만들어도 같은 바이트, 모든 파일 내용이 다르다
- 이어서 늘릴 수 있다 (이미 올린 파일은 duplicate로 건너뜀). 업로드 뒤 Immich 작업 대기열이 빌 때까지 기다린다

## 성능 평가 요약

[eval/scale/README.md](../../eval/scale/README.md)에 표·해석·한계가 있다.

- 파일 수 10배(300 → 3000)에 전체 시간 약 1.8배(92 → 168초). 고정 비용(기동·DB 복원) 약 70초가 대부분
- 개수에 비례하는 단계는 restore(약 0.4GiB/s)와 photos(약 0.22GiB/s)뿐
- photos 기본 timeout 300초: 3000개까지 전부 확인. 299개는 최대 10.6초. 초당 약 4.2MiB 이상이면 300초 안에 299개를 받는다

## 남은 일

- 필수 설정 누락 시험: `env_file`에서 `DB_PASSWORD`를 빼거나(A) 다르게 하거나(B) 파일이 없을 때(C)의 판정 확인. 결과는 [test.md](test.md)와 공유
- photos 표본 검사 확인(선택): timeout을 줄여(예: 20초) "손상 1% 미만" 메시지가 나오는지
- 실제 휴대폰 사진으로 확인 실험(선택)
- `refs.json`에 대응 스냅샷 ID 기록 (형식은 검사 담당과 합의). `make env-clean`이 `refs.json`을 지우지 않는 점도 같이
- 사용자 문서 점검
