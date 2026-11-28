#!/usr/bin/env bash
# testenv 정상 백업의 사본에 고장 스냅샷 4개를 만들고, 고장마다 검증 워크플로를 만든다.
# 절차와 기대 결과: docs/handoff/test.md
#
#   make env      # 먼저 testenv와 정상 백업을 만든다
#   make faults   # 이 스크립트 (NOTIFY=1 이면 워크플로에 Discord 알림 설정 추가)
#
# 원본 testenv 저장소는 건드리지 않는다. 사본과 워크플로는 저장소 밖 폴더에 만든다.
#   WETRUN_FAULTS_DIR  결과 폴더 (기본 ~/wetrun-faults). 실행할 때마다 지우고 새로 만든다
#   NOTIFY=1           워크플로에 notify 추가 (웹훅 주소는 env:WETRUN_DISCORD_WEBHOOK 참조만 쓴다)
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
. testenv/common.sh

require restic "https://restic.readthedocs.io/en/stable/020_installation.html"
# load_env는 testenv/ 안에서 .env.example과 .env를 읽는다
cd testenv
load_env
cd "$root"
: "${RESTIC_PASSWORD:?testenv/.env에 RESTIC_PASSWORD가 없음}"
tag="${TESTENV_BACKUP_TAG:-testenv}"
src_repo="$root/testenv/data/restic-repo"
[ -d "$src_repo" ] || die "testenv 백업이 없음 ($src_repo). 먼저 make env"

F="${WETRUN_FAULTS_DIR:-$HOME/wetrun-faults}"
case "$F" in
  /*) ;;
  *) die "WETRUN_FAULTS_DIR는 절대 경로여야 함 (got: $F)" ;;
esac
case "$F" in
  / | "$HOME" | "$HOME/" | "$root" | "$root"/*) die "WETRUN_FAULTS_DIR로 쓸 수 없는 경로: $F" ;;
esac

rm -rf "$F"
mkdir -p "$F"
cp -R "$src_repo" "$F/repo"
export RESTIC_REPOSITORY="$F/repo"

# 정상 백업 내용을 꺼낸다: data/backup/immich.sql, data/library/...
restic -q restore latest --tag "$tag" --target "$F/src"
cd "$F/src"
dump=data/backup/immich.sql
[ -f "$dump" ] || die "정상 백업에 DB 덤프가 없음 ($dump)"

snap() { restic -q backup data --tag "$1" --host testenv; echo "  + $1"; }

echo "고장 스냅샷 만드는 중 ($F/repo)"

# 1) DB 덤프 손상: 덤프 가운데에 SQL이 아닌 줄을 넣는다
cp "$dump" "$F/dump.orig"
half=$(($(wc -l < "$dump") / 2))
awk -v n="$half" 'NR == n { print "THIS IS NOT SQL;" } { print }' "$F/dump.orig" > "$dump"
snap broken-dump
cp "$F/dump.orig" "$dump"

# 2) DB 덤프 누락
rm "$dump"
snap missing-dump
cp "$F/dump.orig" "$dump"

# 3) 사진 원본 1장 누락 (원본은 data/library/upload/<사용자>/<xx>/<yy>/<id>.png)
photo=$(find data/library/upload -type f -name '*.png' | sort | head -1)
[ -n "$photo" ] || die "정상 백업에 사진 원본이 없음"
cp "$photo" "$F/photo.orig"
rm "$photo"
snap missing-photo

# 4) 사진 원본 1장 손상: 1바이트만 바꾼다 (크기는 같고 해시만 다름)
cp "$F/photo.orig" "$photo"
printf 'X' | dd of="$photo" bs=1 seek=100 conv=notrunc 2>/dev/null
snap corrupt-photo

cd "$F"
rm -rf "$F/src" "$F/dump.orig" "$F/photo.orig"

# 고장마다 워크플로: Immich 프로필을 복사해 경로를 절대 경로로, 저장소와 태그만 바꾼다
T="$root/testenv"
for t in broken-dump missing-dump missing-photo corrupt-photo; do
  out="$F/wf-$t.yaml"
  sed -e "s#\.\./\.\./testenv#$T#g" \
      -e "s#path: $T/data/restic-repo#path: $F/repo#" \
      -e "s#{tag: testenv, select: latest}#{tag: $t, select: latest}#" \
      "$root/profiles/immich/workflow.yaml" > "$out"
  grep -q "path: $F/repo" "$out" && grep -q "tag: $t," "$out" \
    || die "워크플로 변환 실패 ($out). profiles/immich/workflow.yaml 형식이 바뀌었는지 확인"
  if [ "${NOTIFY:-}" = 1 ]; then
    printf '\nnotify:\n  discord: env:WETRUN_DISCORD_WEBHOOK\n  when: [fail, error]\n' >> "$out"
  fi
done

restic snapshots --compact
echo
echo "지운·손상시킨 사진: $(basename "$photo")"
echo "워크플로: $F/wf-<broken-dump|missing-dump|missing-photo|corrupt-photo>.yaml"
echo "실행 예: uv run wetrun run $F/wf-missing-photo.yaml   # 기대: photos 단계 fail (HTTP 404)"
