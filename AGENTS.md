# AGENTS.md

AI 코딩 도구용 안내. 사람용 규칙은 [CONTRIBUTING.md](CONTRIBUTING.md), 역할별 맥락은 [docs/handoff/](docs/handoff/README.md).

## 프로젝트

Wetrun: 기존 restic 백업으로 Docker Compose 서비스를 운영과 분리된 환경에 복구하고,
로그인·조회·다운로드 같은 사용자 동작으로 실제 사용 가능 여부를 판정하는 CLI. Python 3.12, Linux 전용.
첫 대상 서비스는 Immich.

## 명령

```sh
make install   # uv sync
make fmt       # ruff format + ruff check --fix
make lint      # CI와 같은 검사
make test      # pytest
```

변경 후 `make fmt lint test`가 통과해야 한다.

## 반드시 지킬 것

1. `wetrun/`에는 서비스 이름(immich, paperless 등)이나 서비스 고유 SQL·경로·API를 쓰지 않는다.
   서비스 고유 내용은 `profiles/<서비스>/`에만 둔다. CI가 `wetrun/`의 `immich` 문자열을 거부한다.
2. 외부 명령은 `subprocess.run([...])` 리스트 인자로만 호출한다. `shell=True` 금지.
3. 검증이 만든 Docker 자원은 성공·실패·timeout·중단 모두에서 정리한다. 정리는 이번 실행의 라벨이
   붙은 자원만 대상으로 한다. 운영 서비스의 컨테이너·네트워크·볼륨·경로를 절대 건드리지 않는다.
4. 비밀 값(비밀번호, 토큰, restic 비밀번호)을 로그·리포트·알림·테스트 픽스처에 남기지 않는다.
   `.env`, 데이터 폴더, restic 저장소를 커밋하지 않는다. 이 저장소는 공개다.
5. 미실행·건너뛴 필수 검사를 성공으로 처리하지 않는다.
6. 새 런타임 의존성을 추가하지 않는다 (현재 PyYAML 하나). 표준 라이브러리로 먼저 해결한다.
7. 판정 규칙·정리 로직을 바꾸면 테스트를 함께 추가한다.

## 담당 폴더

자기 담당 밖의 폴더를 고쳐야 하면 먼저 사용자에게 확인한다.

| 폴더 | 담당 |
|---|---|
| `wetrun/` (단, `steps/`·`report.py`·`notify.py` 제외) | 실행기 (차은호) |
| `wetrun/steps/`, `wetrun/report.py`, `wetrun/notify.py`, `profiles/` | 검사·출력 (조정민) |
| `testenv/`, `eval/` 성능·사용자 평가, 사용자 문서 | 환경 (정순준) |
| `faults/`, `tests/` 계약·격리 테스트, `eval/` 시나리오 평가 | 테스트 (김영모) |

## 커밋·PR

- Conventional Commits: `<type>(<scope>): <요약>`. 요약은 한국어 가능.
  type: `feat` `fix` `test` `docs` `refactor` `chore`
- `main`에 직접 push하지 않는다. 브랜치 `<type>/<짧은-설명>` → PR → CI 통과 → squash merge.
- 커밋·push·PR 생성은 사용자가 요청할 때만 한다.
