# handoff: 검사·출력 (조정민)

담당: `wetrun/steps/`, `wetrun/report.py`, `wetrun/notify.py`, `profiles/`

실행기 담당과의 계약: [docs/contract.md](../contract.md) (검사 컨테이너 입출력, 워크플로 YAML, 판정 규칙).

## 현재 상태 (2026-11-14)

| 부분 | 파일 | 상태 |
|---|---|---|
| 검사 공통 입출력 | `steps/_common.py` | 완료 (#14) |
| 서비스 응답 확인 | `steps/http.py` | 완료 (#14) |
| 파일 대조 | `steps/ref_files.py` | 완료 (#21, #22) |
| Immich 워크플로 | `profiles/immich/workflow.yaml` | 완료 (#23). WSL2 Ubuntu에서 `wetrun run` 전 단계 pass (검사 컨테이너 안 ref_files 포함) |
| 리포트 | `report.py` | 완료 (#24). 실행기 연결(`__main__.py`)은 실행기 담당과 합의 필요 |
| 알림 | `notify.py` | 완료 (#26). `wetrun run` 연결 (#29). 카드 형식으로 바꿈 |
| DB 질의 | `steps/db_query.py` | v0.1 보류 (표준 라이브러리로 DB 접속 불가) |

## 내장 검사

모든 내장 검사는 `_common.run(check)`으로 실행한다. `check`가 `(상태, 메시지, 근거)`를 돌려주면
`run`이 `result.json`을 쓰고 종료 코드(0 pass, 1 fail, 2 error)로 끝낸다. 예외는 잡아서 error로 끝낸다.
검사는 `timeout` 안에 스스로 끝낸다 (#12).

### http

주소에 GET을 보내 기대한 상태 코드가 마감 안에 오는지 본다.

| 키 | 기본값 | 뜻 |
|---|---|---|
| `url` | (필수) | 요청할 주소 |
| `expect_status` | 200 | 기대하는 상태 코드 |
| `interval` | 2 | 다시 시도하는 간격(초), 0보다 커야 함 |

리다이렉트(3xx)는 따라간 뒤의 상태 코드로 판정한다. 그래서 `expect_status: 302`는 통과하지 않는다.

### ref_files

복구한 서비스에 로그인해 파일이 `refs.json`과 같은지 본다.

1. 로그인
2. 목록 대조: 기준 파일이 모두 있는지 (파일 이름), 앨범 파일 수가 줄지 않았는지
3. 체크섬 대조: 서비스가 기록한 체크섬과 기준 SHA-1을 전부 비교
4. 다운로드 대조: 원본을 받아 SHA-1 계산. 무작위 순서로 timeout까지 최대한 많이 본다. 전부 보면 "전부 확인", 3의 법칙이 요구하는 수(1%면 299) 이상이면 "1% 미만", 그보다 적으면 error

서비스 고유의 API 경로와 응답 필드 이름은 워크플로가 알려 준다. 키는 `ref_files.py` 맨 위 설명을 본다.

| 판정 | 언제 |
|---|---|
| `pass` | 모두 일치 |
| `fail` | 로그인 거부, 파일 빠짐, 체크섬·다운로드 해시 다름, 앨범 파일 줄어듦, 서비스 무응답·오류 응답 |
| `error` | 설정 오류, 응답에 설정한 필드가 없음, 불일치 없이 3의 법칙이 요구하는 수만큼 못 봄 |

## 정한 것과 근거

| 결정 | 근거 |
|---|---|
| 체크섬은 전부, 다운로드는 시간 안에서 최대한 | 체크섬은 DB 기록, 다운로드는 실제 파일 확인. 다운로드는 느리다. "몇 장부터 샘플" 같은 경계 숫자 대신 무작위 순서로 timeout까지 보면, 어디서 멈춰도 공정한 샘플이 된다. 최소한 3의 법칙(기본 1%·95% → 299개)만큼은 봐야 pass |
| 3의 법칙을 그대로 씀 | 파일 수가 무한하다고 보고 계산한 값이라, 파일이 적으면 필요한 수보다 조금 많이 요구한다 (안전한 쪽) |
| 다운로드 순서는 매번 다른 시드로 정하고 evidence에 남김 | 여러 번 돌리면 더 많은 파일을 보고, 같은 시드로 다시 돌려 볼 수 있다 |
| 리포트에 "손상 없음"이라고 쓰지 않음 | 샘플이면 "1% 미만 (95% 신뢰도, 시드 N)", 전부면 "N개 전부 확인"처럼 확인한 범위를 쓴다 |
| 파일은 이름과 SHA-1로 짝지음 | asset id는 복구할 때마다 다르다 (testenv/README.md) |
| 기준보다 파일이 많으면 fail 아님 | 백업이 기준 데이터보다 나중일 수 있다. 개수만 남긴다 |
| 다운로드는 64KB씩 읽으며 해시 | 검사 컨테이너는 읽기 전용이고 메모리 제한이 있다 |
| Immich 덤프 복원은 두 줄을 걸러 `ON_ERROR_STOP` | `pg_dumpall --clean` 덤프가 접속 사용자를 지우려다 멈춘다 (#13) |
| Immich 기동에서 머신러닝 제외 | 파일 확인에 쓰지 않고 메모리가 약 35% 준다 (#13) |
| 리포트 요약에는 메시지만, stderr는 JSON에만 | 요약을 짧게 유지하고 근거는 JSON에서 본다 (#13) |
| 요약·알림 맨 위에 "할 일" 한 줄 | 결과를 본 사람이 바로 어느 단계를 볼지 안다. error에는 "백업이 망가졌다는 뜻은 아님"을 붙인다: fail과 헷갈리면 멀쩡한 백업을 의심하게 된다 |
| 비밀 값은 메시지·evidence 글자·정리 오류만 가림 | 리포트 전체 글자를 바꾸면 비밀번호가 `pass`나 숫자일 때 판정이 바뀌거나 JSON이 깨진다 (#24) |
| 알림은 기본 fail·error, 정리 실패는 항상 | 운영자가 조치해야 하는 경우만 알린다 |
| 알림 실패는 판정을 바꾸지 않음 | 알림은 부가 기능이다. `send()`는 예외를 던지지 않고 (보냈는지, 이유)만 돌려준다 |
| 알림에서 멘션 끔 (`allowed_mentions`) | 단계 메시지에 `@everyone` 같은 글자가 섞여도 아무도 호출하지 않게 |

## 리포트와 알림

모든 함수는 `secrets`(가릴 비밀 값 목록)를 받는다. 실행기 연결 후에는 실행기가 넘긴다
(지금은 `__main__.py`가 report·notify를 부르지 않는다).

- `report.to_dict(result, secrets)`: JSON 리포트. `verdict`, `exit_code`를 계산해 넣는다
- `report.summary(result, secrets)`: 사람이 읽는 요약
- `report.next_actions(data)`: 할 일 목록. 통과면 빈 목록
- `report.save(result, dir, secrets)`: `<dir>/<run_id>.json` (0600)
- `notify.send(url, result, when, secrets, title=, report_path=)`: Discord 웹훅. 웹훅 주소는 출력하지 않는다. https만 보낸다.
  `title`(서비스 이름)과 `report_path`(리포트 위치)는 부르는 쪽이 넘긴다

알림은 **한 줄 글자 + 카드 하나**다. 시안 네 가지를 실제 채널(PC·휴대폰)에 보내 비교해 정했다.

```
❌ **FAIL · immich** — `photos` 단계               ← 한 줄 글자 (휴대폰 푸시 미리보기)
┃ 백업에 문제가 있어요                             ← 카드 제목, 판정 색 막대 (pass 초록 · fail 빨강 · error 주황)
┃ > 다운로드한 원본이 다른 파일 1개                ← 원인
┃ 할 일 백업 원본과 백업 작업을 확인해 주세요.
┃ 단계  ✅ restore       1.4초                     ← 고정폭 상자로 줄 맞춤
┃       ❌ photos        1.5초
┃ 리포트 ~/.local/share/wetrun/runs/<실행 ID>.json  ← fail·error만
┃ <컴퓨터 이름> · 스냅샷 ef78df4f · 총 75.8초 · 시각
```

| 정한 것 | 이유 |
|---|---|
| 원인은 카드에 한 번만, 한 줄 글자엔 판정·서비스·단계까지 | 같은 말이 두 번 나오면 눈이 갈 곳을 잃는다 |
| 제목은 짧은 해요체, error엔 "백업이 망가졌다는 뜻은 아니에요." | 새벽에 받은 사람이 먼저 알고 싶은 건 "데이터가 날아갔나, 검사기가 멈췄나" |
| 단계는 고정폭 상자 | 상자 없는 두 칸 방식보다 줄이 반듯하다 (시안 비교) |
| pass는 무음 (`flags: 4096`), 정리 실패가 섞이면 울림 | "알림이 울리면 할 일이 있다" |
| 이름은 "Wetrun"으로 덮어씀 (`username`) | 사용자가 웹훅 이름을 바꿀 필요가 없다 |
| 리포트 JSON 첨부는 하지 않음 | 비밀 값은 가려도 내부 경로·호스트가 외부로 나간다 |

Discord 제한(글자 2000자, 칸 1024자, 카드 6000자)을 넘으면 칸마다 잘라 넣는다.
카드 폭은 Discord가 글 길이로 정하고 지정할 수 없다. 휴대폰에서는 항상 화면 폭이다.
알림에는 컴퓨터 이름이 들어간다. 비밀 값은 아니지만 공개 채널로 보내면 내부 호스트 이름이 드러난다.

요약 예 (덤프 복원 실패):

```
Wetrun 결과: FAIL (종료 코드 1)
할 일: 백업이나 복구한 데이터에 문제가 있음. restore-db 단계를 확인 (근거는 JSON 리포트)
실행 20261114-053430-e72399 · 스냅샷 ef78df4f · 14.0초

  pass     restore        1.7초  스냅샷 복원
  pass     up-db          6.7초  서비스 기동
  fail     restore-db     3.1초  명령이 실패함
  skipped  up             0.0초  앞 필수 단계가 통과하지 못함
```

워크플로의 알림 설정 (실행기 연결 후):

```yaml
notify:
  discord: env:WETRUN_DISCORD_WEBHOOK
  when: [fail, error]   # YAML에서 `on`은 true로 읽혀서 `when`을 쓴다. `when: fail`처럼 하나만 써도 된다
```

`when`에 쓸 수 있는 값은 `notify.WHEN_CHOICES`(pass, fail, error)다. 틀린 값은 check-input에서 거르는 게 맞다 (실행기 연결 때 합의).

## 알려진 한계

- ref_files는 앨범의 파일 수만 비교한다 (어떤 파일이 들었는지는 보지 않음)
- 사진·동영상 등 종류별 최소 1개 샘플링은 없다 (testenv는 PNG뿐)
- `profiles/immich/workflow.yaml`은 testenv 생성물(`../../testenv/`)을 가리킨다. 다른 Immich에는 경로를 바꿔 쓴다
- 실제 크기 사진으로 다운로드 속도를 재지 않았다 (testenv는 작은 PNG 5장). 사진이 많으면 ref_files `timeout`을 늘려야 할 수 있다
- 알림은 실제 Discord 채널(PC·휴대폰)에서 확인했다. pass는 무음, fail은 휴대폰 푸시가 울림. error 푸시는 따로 확인하지 않았다
- 기본 알림은 실패할 때만이라, wetrun이 아예 안 돌아도 조용하다 ("dead man's switch" 문제: 살아 있다는 신호가 없으면 멈춘 걸 모른다). 실행기 쪽에서 "잡지 않기로" 정했다 (design-decisions 12절). 매일 결과를 받으려면 `when: [pass, fail, error]`

## 나중에 할 것

- 스냅샷 나이 표시와 "백업이 오래됨" 경고: 백업이 멈춰도 복구 검증은 매일 pass다. 실행기가 스냅샷 시각을 결과에 넣어야 한다 (#37 warnings와 함께 제안)
- 연속 실패 횟수, 마지막 성공 시각: 실행 이력 읽기(`report.load_history`, #37)가 생기면
- 실패 알림에 역할 멘션: 지금은 멘션을 모두 끈다. 켜려면 역할 ID를 적을 설정 키가 필요하다

## 실행기 없이 검사 시험하기

```sh
mkdir -p /tmp/wr && cp testenv/refs.json /tmp/wr/   # step.json은 아래처럼 만든다
WETRUN_DIR=/tmp/wr uv run python -m wetrun.steps.ref_files; cat /tmp/wr/out/result.json
```

`/tmp/wr/step.json`은 `workflow.yaml`의 ref_files 단계(`photos`)를 JSON으로 옮겨 만든다.
`url`은 `http://localhost:2283`으로 바꾸고, `env:` 참조는 실행기가 바꿔 주는 것이라 실제 값을 넣는다
(testenv 계정 비밀번호는 `.env.example`의 `TESTENV_ADMIN_PASSWORD`).

testenv는 `localhost:2283`에서 접속한다 (워크플로의 `immich-server:2283`은 검사 컨테이너 안 주소).
