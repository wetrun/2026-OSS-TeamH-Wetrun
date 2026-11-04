#!/usr/bin/env bash
# testenv Immich를 멈춘다. --clean을 주면 data/(사진, DB, 백업)까지 지운다.
set -euo pipefail
cd "$(dirname "$0")"

if [ -f docker-compose.yml ]; then
  docker compose down
fi

if [ "${1:-}" = "--clean" ] && [ -d data ]; then
  # data/postgres는 컨테이너 사용자(999) 소유라 일반 rm으로 못 지운다.
  # sudo 대신 컨테이너 안에서 지운다.
  docker run --rm -v "$PWD/data:/data" busybox sh -c 'rm -rf /data/* /data/.[!.]*'
  rmdir data
  echo "data/ 삭제 완료"
fi
