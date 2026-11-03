# 온보딩

처음 합류한 팀원이 개발 환경을 갖추고 첫 PR을 올리기까지의 안내.
규칙의 세부 내용은 [CONTRIBUTING.md](../CONTRIBUTING.md)를 따른다.

## 1. 이 프로젝트는

Wetrun은 기존 restic 백업으로 Docker Compose 서비스를 운영과 분리된 환경에 복구해 보고,
로그인·조회·다운로드 같은 사용자 동작까지 자동으로 검사하는 도구다.
"백업이 됐다"가 아니라 "백업으로 실제로 다시 쓸 수 있다"를 확인하는 것이 목표다.
첫 대상 서비스는 Immich(셀프호스팅 사진 관리)다.

## 2. 누가 무엇을 맡나

| 역할 | 담당 | 주로 보는 폴더 |
|---|---|---|
| 실행기 | 차은호 | `wetrun/` (단, `steps/`·`report.py`·`notify.py` 제외) |
| 검사·출력 | 조정민 | `wetrun/steps/`, `wetrun/report.py`, `wetrun/notify.py`, `profiles/` |
| 환경·성능·사용자 평가·문서 | 정순준 | `testenv/`, `eval/`, `docs/` |
| 테스트·평가 | 김영모 | `faults/`, `tests/`, `eval/` |

실행기와 검사는 검사 컨테이너 계약(입출력 약속)으로만 연결된다. 계약 문서는 합의 후 `docs/`에 추가한다.

## 3. 개발 환경 준비

Wetrun은 Linux에서 동작한다. Windows는 WSL2 안에서, macOS는 그대로 개발한다.

### Windows

1. PowerShell(관리자)에서 `wsl --install` 실행 → 재부팅 → Ubuntu 사용자 생성
2. [Docker Desktop](https://www.docker.com/products/docker-desktop/) 설치
   → Settings → Resources → WSL Integration → Ubuntu 켜기
3. 이후 모든 작업은 **Ubuntu 터미널**에서 한다.
   ```sh
   sudo apt update && sudo apt install -y git make restic
   curl -LsSf https://astral.sh/uv/install.sh | sh   # 또는 pipx install uv
   ```

### macOS

1. `xcode-select --install` (git, make 포함)
2. Docker Desktop 또는 OrbStack 설치
3. ```sh
   brew install uv restic
   ```

### 확인

```sh
docker compose version   # v2 이상
restic version
uv --version
make --version
```

## 4. 저장소 받기

```sh
cd ~                     # Windows는 반드시 WSL 홈. /mnt/c 아래에 두지 않는다
git clone https://github.com/wetrun/2026-OSS-TeamH-Wetrun.git
cd 2026-OSS-TeamH-Wetrun
make install             # uv sync: Python 3.12와 의존성 설치
make lint test           # 모두 통과하면 준비 완료
```

push 권한이 없으면 `wetrun` 조직 초대를 수락했는지 확인한다.

## 5. 에디터

Windows에서도 터미널로만 작업할 필요는 없다. 파일과 실행은 WSL 안에 두고, 편집은 Windows의 IDE로 한다.

### VS Code (추천)

- 확장: **Ruff**, **Python**, (Windows) **WSL**
- Windows: Ubuntu 터미널의 저장소 폴더에서 `code .` 실행. Windows에 창이 뜨고 탐색기·편집기·Git 패널·내장 터미널이 모두 WSL 안에서 동작한다.
- 설정: Format on Save 켜기, 기본 포맷터를 Ruff로 지정

### PyCharm

- Windows: WSL 안의 프로젝트(`\\wsl$\Ubuntu\home\<사용자>\2026-OSS-TeamH-Wetrun`)를 열고,
  인터프리터를 WSL의 `.venv/bin/python`으로 지정한다. WSL 지원 범위는 사용하는 에디션에서 확인한다.
- Ruff 플러그인을 설치하거나, 커밋 전 `make fmt`를 실행한다.

### 공통

- `make`·`wetrun` 명령은 IDE 내장 터미널(WSL)에서 실행한다.
- GitHub Desktop 같은 Windows Git 도구로 `\\wsl$` 경로를 다루면 느리고 줄바꿈 문제가 생길 수 있다. IDE의 Git 기능이나 WSL 터미널의 `git`을 쓴다.

## 6. 첫 PR까지

```sh
git switch -c docs/hello-<이름>
# 작업
make fmt lint test
git commit -m "docs: 온보딩 확인"
git push -u origin HEAD
gh pr create --fill     # GitHub CLI(gh)가 있을 때. 없으면 GitHub 웹에서 PR 생성
```

- 커밋·PR 제목: `<type>(<scope>): <요약>` (예: `feat(runner): 실패 시에도 자원 정리`)
- `main`에 직접 push하지 않는다. PR → CI 통과 → squash merge

## 7. 먼저 읽을 문서

1. [handoff/](handoff/README.md): 공통 배경·일정, 자기 역할 파일
1. [CONTRIBUTING.md](../CONTRIBUTING.md): 코드·커밋·PR 규칙
2. `testenv/` 안내: 준비 중 (환경 담당)

## 8. 자주 겪는 문제

| 증상 | 원인·해결 |
|---|---|
| 스크립트 실행 시 `$'\r': command not found` | CRLF 줄바꿈. WSL 홈에 clone했는지 확인하고, `git add --renormalize .` |
| WSL에서 파일 접근이 매우 느림 | `/mnt/c` 아래에서 작업 중. WSL 홈(`~/`)으로 옮긴다 |
| `Makefile: *** missing separator` | 명령 줄 들여쓰기가 스페이스. 탭으로 바꾼다 |
| `Cannot connect to the Docker daemon` | Docker Desktop이 꺼져 있거나 WSL Integration이 꺼져 있음 |
| Apple Silicon에서 이미지 실행 실패 | 이미지가 arm64를 지원하는지 확인. 지원하지 않으면 Linux 머신에서 테스트 |
| CI의 ruff 실패 | `make fmt` 후 다시 커밋 |
| CI의 "서비스 이름이 없어야 함" 실패 | `wetrun/`에 서비스 고유 내용이 들어감. `profiles/<서비스>/`로 옮긴다 |
