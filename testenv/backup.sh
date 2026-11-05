#!/usr/bin/env bash
# testenv Immich를 restic으로 백업한다: DB 덤프 → restic 저장소 준비 → 덤프와 사진 폴더 백업
set -euo pipefail
cd "$(dirname "$0")"
. ./common.sh

require_docker
require restic "download 0.18+ from https://github.com/restic/restic/releases (apt version is too old)"

# 1. 설정 읽기: .env.example을 기본값으로, .env가 있으면 그 값으로 덮어쓴다
load_env

# 2. Immich DB가 실행 중인지 확인
if ! docker compose ps --status running --services 2>/dev/null | grep -qx database; then
  die "Immich DB is not running. Run make env-up first"
fi

# 3. DB 덤프: 실행 중인 DB 파일을 그대로 복사하면 일관성이 깨질 수 있어 pg_dumpall로 뽑는다
mkdir -p data/backup
dump=data/backup/immich.sql
docker compose exec -T database \
  pg_dumpall --clean --if-exists --username="$DB_USERNAME" > "$dump.tmp"
if [ ! -s "$dump.tmp" ]; then
  rm -f "$dump.tmp"
  die "DB dump is empty"
fi
mv "$dump.tmp" "$dump"
echo "DB dump: $dump ($(du -h "$dump" | cut -f1))"

# 4. restic 저장소 준비: 없으면 만들고, 있는데 열리지 않으면 비밀번호 문제로 알린다
export RESTIC_REPOSITORY RESTIC_PASSWORD
if [ ! -f "$RESTIC_REPOSITORY/config" ]; then
  restic init
elif ! restic cat config >/dev/null 2>&1; then
  die "cannot open restic repository (${RESTIC_REPOSITORY}). Check that RESTIC_PASSWORD in .env matches the one used to create it"
fi

# 5. 백업: DB 덤프 + 사진 폴더.
# --host를 고정해서 누구 컴퓨터에서 만들어도 스냅샷 정보가 같게 한다.
restic backup "$dump" "$UPLOAD_LOCATION" \
  --tag "$TESTENV_BACKUP_TAG" --host testenv

# 6. 확인
restic snapshots --tag "$TESTENV_BACKUP_TAG" --latest 1
restic check
echo "backup done: repository testenv/${RESTIC_REPOSITORY#./}, tag $TESTENV_BACKUP_TAG ($(restic version | cut -d' ' -f1-2))"
