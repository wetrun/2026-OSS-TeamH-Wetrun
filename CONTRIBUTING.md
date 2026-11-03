# 기여 규칙

## 개발 환경
- Linux, macOS, Windows(WSL2 Ubuntu). Windows는 repo를 WSL 홈(`~/`)에 clone한다. `/mnt/c`는 쓰지 않는다.
- 필요 도구: Docker(Compose v2), restic, uv, make
- `make install` → `make lint test`

## 코드 스타일
- ruff로 포맷·검사한다: `make fmt`. CI의 `make lint`가 실패하면 머지하지 않는다.
- 타입 힌트는 함수 시그니처에 붙인다.
- `wetrun/` 안에는 서비스 이름(immich 등)을 쓰지 않는다. 서비스 고유 내용은 `profiles/<서비스>/`에만 둔다.
- 외부 명령은 `subprocess.run([...])`에 리스트 인자로 호출한다. `shell=True` 금지.
- 비밀 값은 로그·리포트·알림에 직접 출력하지 않는다.
- 판정 규칙·정리 로직을 바꾸는 PR은 테스트를 함께 넣는다.

## 커밋 메시지
Conventional Commits. 요약은 한국어 가능, 50자 안쪽, 마침표 없음.

```
<type>(<scope>): <요약>

feat(runner): 실패 시에도 자원 정리
fix(immich): 원본 다운로드 경로 수정
```
- type: `feat` `fix` `test` `docs` `refactor` `chore`
- scope: `runner` `restic` `steps` `report` `immich` `paperless` `testenv` `faults` `eval` `ci`

## 브랜치·PR
- `main`에 직접 push하지 않는다. 브랜치 이름은 `<type>/<짧은-설명>`. 예: `feat/l0-ref-files`
- 머지 조건: CI 통과 (승인 리뷰는 필수 아님). squash merge만 사용하며, PR 제목을 커밋 메시지 형식으로 쓴다.
- PR은 작게 만든다 (diff 400줄 이하 권장).

## 이슈
- Assignee를 지정한다.
- 라벨: `runner` `checks` `testenv` `test` `docs`
