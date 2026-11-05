#!/usr/bin/env bash
# testenv Immich를 멈춘다. --clean을 주면 data/(사진, DB, 백업)까지 지운다.
# --clean은 지우기 전에 확인을 받는다. 묻지 않고 지우려면 YES=1 (make env-clean YES=1)
set -euo pipefail
cd "$(dirname "$0")"
. ./common.sh

clean=false
[ "${1:-}" = "--clean" ] && clean=true

# 지울 data/가 있으면 멈추기 전에 먼저 확인한다 (아니라고 하면 아무것도 바꾸지 않는다)
if $clean && [ -d data ] && [ "${YES:-}" != "1" ]; then
  [ -t 0 ] || die "cannot ask for confirmation (no terminal). To delete, set YES=1 (make env-clean YES=1)"
  read -r -p "This deletes everything in testenv/data/ (photos, DB, backups). Continue? [y/N] " answer
  case "$answer" in
    y | Y | yes) ;;
    *) echo "cancelled. nothing was deleted"; exit 0 ;;
  esac
fi

if [ -f docker-compose.yml ]; then
  require_docker
  load_env  # COMPOSE_PROJECT_NAME을 up.sh와 같게 읽는다
  docker compose down
fi

if $clean && [ -d data ]; then
  require_docker
  # data/postgres는 컨테이너 사용자(999) 소유라 일반 rm으로 못 지운다.
  # sudo 대신 컨테이너 안에서 지운다.
  docker run --rm -v "$PWD/data:/data" busybox sh -c 'rm -rf /data/* /data/.[!.]*'
  rmdir data
  echo "deleted data/"
fi
