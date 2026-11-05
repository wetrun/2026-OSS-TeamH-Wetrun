# testenv 스크립트 공통 함수. up.sh, down.sh가 source해서 쓴다 (직접 실행하지 않는다).

# 오류 메시지를 출력하고 멈춘다
die() {
  echo "error: $*" >&2
  exit 1
}

# 명령이 없으면 설치 방법을 알려 주고 멈춘다. 사용: require <명령> "<설치 안내>"
require() {
  command -v "$1" >/dev/null 2>&1 || die "$1 not found. Install: $2"
}

# Docker와 Compose v2가 쓸 수 있는 상태인지 확인한다
require_docker() {
  require docker "Docker Desktop, then enable Ubuntu in Settings > Resources > WSL Integration"
  docker info >/dev/null 2>&1 \
    || die "cannot connect to Docker. Check that Docker Desktop is running and WSL Integration is enabled for Ubuntu"
  docker compose version >/dev/null 2>&1 \
    || die "docker compose (v2) not found. Update Docker Desktop"
}

# .env.example을 기본값으로, .env가 있으면 그 값으로 덮어써서 환경 변수로 읽는다.
# 값에 따옴표를 써도 같은 값이 되도록 셸 문법으로 읽는다.
# Windows 편집기로 저장해 줄 끝에 \r이 붙으면 버전·비밀번호 끝에 \r이 섞여 다운로드나
# 로그인이 실패한다. docker compose도 .env를 직접 읽으므로 .env의 \r은 파일에서 지운다.
# macOS 기본 bash 3.2와 BSD 도구에서도 동작하도록 `. <(...)`와 `sed -i`를 쓰지 않는다.
load_env() {
  if [ -f .env ] && grep -q $'\r' .env; then
    tr -d '\r' < .env > .env.tmp && mv .env.tmp .env
    echo "removed Windows line endings (\\r) from .env"
  fi
  set -a
  eval "$(tr -d '\r' < .env.example)"
  if [ -f .env ]; then
    eval "$(tr -d '\r' < .env)"
  fi
  set +a
}
