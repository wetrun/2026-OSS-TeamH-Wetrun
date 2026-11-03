#!/usr/bin/env bash
# testenv Immich를 띄운다: compose 파일 받기 → .env 준비 → data 폴더 생성 → 실행 → healthy 대기
set -euo pipefail
cd "$(dirname "$0")"

# 1. .env 준비 (이미 있으면 건드리지 않는다)
if [ ! -f .env ]; then
  cp .env.example .env
  echo ".env.example → .env 복사"
fi

# 2. .env의 버전으로 Immich 공식 docker-compose.yml 받기
version="$(grep '^IMMICH_VERSION=' .env | cut -d= -f2)"
if [ -z "$version" ]; then
  echo "오류: .env에 IMMICH_VERSION이 없다" >&2
  exit 1
fi
echo "Immich ${version}의 docker-compose.yml 받는 중"
curl -fsSL --retry 3 -o docker-compose.yml \
  "https://github.com/immich-app/immich/releases/download/${version}/docker-compose.yml"

# 3. data 폴더를 Docker보다 먼저 만든다 (Docker가 만들면 root 소유가 되어 Permission denied가 난다)
mkdir -p data/library data/postgres data/backup

# 4. 실행하고 모든 컨테이너가 healthy가 될 때까지 기다린다
docker compose up -d --wait
docker compose ps
echo "준비 완료: http://localhost:2283"
