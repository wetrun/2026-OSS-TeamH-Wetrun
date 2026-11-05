#!/usr/bin/env bash
# testenv Immich를 띄운다: .env 준비 → compose 파일 준비 → data 폴더 생성 → 실행 → healthy 대기
set -euo pipefail
cd "$(dirname "$0")"
. ./common.sh

require_docker

# 1. .env 준비 (이미 있으면 건드리지 않는다)
if [ ! -f .env ]; then
  cp .env.example .env
  echo "copied .env.example to .env"
fi
load_env
version="${IMMICH_VERSION:-}"
[ -n "$version" ] || die "IMMICH_VERSION is not set in .env"

# 2. 그 버전의 Immich 공식 docker-compose.yml 준비.
# 버전별 파일로 한 번만 받아 두고, 다음부터는 네트워크 없이 그 파일을 쓴다.
cached="docker-compose.${version}.yml"
if [ ! -s "$cached" ]; then
  require curl "sudo apt install -y curl"
  echo "downloading docker-compose.yml for Immich ${version}"
  curl -fsSL --retry 3 -o "$cached.tmp" \
    "https://github.com/immich-app/immich/releases/download/${version}/docker-compose.yml" \
    || { rm -f "$cached.tmp"; die "failed to download docker-compose.yml. Check your network (VPN etc.) and IMMICH_VERSION (${version})"; }
  mv "$cached.tmp" "$cached"
fi

# 공식 compose는 '2283:2283'(모든 네트워크 주소)으로 열어 같은 네트워크의 다른 기기도 접속할 수 있다.
# TESTENV_BIND_ADDR(기본 127.0.0.1, 이 컴퓨터만)에만 열도록 복사본만 고친다. 캐시 원본은 그대로 둔다.
# sed -i는 GNU/BSD 문법이 달라 쓰지 않는다 (common.sh 참고).
bind="${TESTENV_BIND_ADDR:-127.0.0.1}"
case "$bind" in
  "" | *[!0-9.]*) die "TESTENV_BIND_ADDR must be an IPv4 address like 127.0.0.1 or 0.0.0.0 (got: ${bind})" ;;
esac
# 공식 compose는 container_name(immich_server 등)도 고정해 한 컴퓨터에 Immich를 하나만 띄울 수 있다.
# 그 줄을 지우면 이름이 `<프로젝트이름>-<서비스>-1`(예: wetrun-testenv-database-1)이 되어
# 실행기의 복구 환경과 함께 띄울 수 있다. 스크립트는 `docker compose exec database`처럼 서비스 이름을 쓰므로 영향 없음.
sed -e "s/'2283:2283'/'${bind}:2283:2283'/" \
    -e "/^[[:space:]]*container_name:/d" \
    "$cached" > docker-compose.yml.tmp
mv docker-compose.yml.tmp docker-compose.yml
# Immich가 compose 형식을 바꾸면 위 sed가 조용히 아무것도 안 바꾼다 → 그대로 진행하지 않게 멈춘다
grep -q "'${bind}:2283:2283'" docker-compose.yml \
  || die "could not set the port address in docker-compose.yml (did the format change in Immich ${version}?)"
! grep -q "container_name:" docker-compose.yml \
  || die "could not remove container_name from docker-compose.yml (did the format change in Immich ${version}?)"

# 3. data 폴더를 Docker보다 먼저 만든다 (Docker가 만들면 root 소유가 되어 Permission denied가 난다)
mkdir -p data/library data/postgres

# 4. 실행하고 모든 컨테이너가 healthy가 될 때까지 기다린다
docker compose up -d --wait
docker compose ps
echo "ready: http://localhost:2283 (listening on ${bind})"
