#!/bin/sh
# Nextcloud 시험 환경: 운영 역할 Nextcloud(MariaDB) + 파일 3개 + restic 백업 + 정답지(refs.json)
# 실행 위치: 이 폴더. 값은 모두 시험 전용이다. 필요: docker, curl, python3
# 파일이 www-data(33) 소유라 백업은 실제 운영처럼 root 권한(restic 컨테이너)으로 한다
set -e
cd "$(dirname "$0")"
N=$(pwd)
mkdir -p html db backup
cat > .env <<ENV
MYSQL_PASSWORD=nc-db-pw
MARIADB_ROOT_PASSWORD=nc-root-pw
NEXTCLOUD_ADMIN_PASSWORD=nc-admin-pw
ENV
chmod 600 .env
docker compose -p nextcloud-prod up -d --wait
until curl -s -H 'Host: localhost' http://127.0.0.1:8081/status.php | grep -q '"installed":true'; do sleep 3; done

head -c 300000 /dev/urandom > /tmp/photo.jpg; printf 'Wetrun 문서\n' > /tmp/note.txt
head -c 50000 /dev/urandom > /tmp/report.pdf
for f in photo.jpg note.txt report.pdf; do
  curl -sf -u wetrun:nc-admin-pw -H 'Host: localhost' -T /tmp/$f \
    http://127.0.0.1:8081/remote.php/dav/files/wetrun/$f
done
python3 -c "
import hashlib, json
print(json.dumps({'user': 'wetrun', 'files': {f: hashlib.sha1(open('/tmp/' + f, 'rb').read()).hexdigest()
      for f in ('photo.jpg', 'note.txt', 'report.pdf')}}))" > refs.json

# 백업: 유지보수 모드 → DB 덤프 → 파일·덤프 백업 (root) → 유지보수 모드 해제 (Nextcloud 공식 절차)
occ() { docker exec nextcloud su -s /bin/sh www-data -c "php occ $*"; }
occ maintenance:mode --on
docker exec nextcloud-db sh -c 'mariadb-dump -u root -p"$MARIADB_ROOT_PASSWORD" --single-transaction nextcloud' \
  > backup/nextcloud.sql
R="docker run --rm -v $N:/src:ro -v $N/restic-repo:/repo -e RESTIC_PASSWORD=nc-restic-pw restic/restic:0.18.0 -r /repo"
$R init
$R backup -q --tag nextcloud --host nextcloud /src/html /src/backup
occ maintenance:mode --off
docker run --rm -v "$N/restic-repo:/repo" alpine:3 chown -R "$(id -u):$(id -g)" /repo
printf 'RESTIC_PASSWORD=nc-restic-pw\nNEXTCLOUD_ADMIN_PASSWORD=nc-admin-pw\n' > secrets.env
chmod 600 secrets.env
echo "준비 끝: set -a; . ./secrets.env; set +a; wetrun run workflow.yaml"
