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
cp "$cached" docker-compose.yml

# 3. data 폴더를 Docker보다 먼저 만든다 (Docker가 만들면 root 소유가 되어 Permission denied가 난다)
mkdir -p data/library data/postgres

# 4. 실행하고 모든 컨테이너가 healthy가 될 때까지 기다린다
docker compose up -d --wait
docker compose ps
echo "ready: http://localhost:2283"
