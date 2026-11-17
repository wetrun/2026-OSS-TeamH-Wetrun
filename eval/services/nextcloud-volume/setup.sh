#!/bin/sh
# 이름 있는 볼륨 방식 Nextcloud(공식 예시 형태) 시험 환경: 운영 역할 + 파일 3개 + 볼륨 백업 + 정답지
# 실행 위치: 이 폴더. 값은 모두 시험 전용이다. 필요: docker, curl, python3
set -e
cd "$(dirname "$0")"
V=$(pwd)
mkdir -p backup
printf 'MYSQL_PASSWORD=nc-db-pw\nMARIADB_ROOT_PASSWORD=nc-root-pw\nNEXTCLOUD_ADMIN_PASSWORD=nc-admin-pw\n' > .env
chmod 600 .env
docker compose -p ncvol-prod up -d --wait
until curl -s -H 'Host: localhost' http://127.0.0.1:8082/status.php | grep -q '"installed":true'; do sleep 3; done
head -c 300000 /dev/urandom > /tmp/photo.jpg; printf 'Wetrun 문서\n' > /tmp/note.txt
head -c 50000 /dev/urandom > /tmp/report.pdf
for f in photo.jpg note.txt report.pdf; do
  curl -sf -u wetrun:nc-admin-pw -H 'Host: localhost' -T /tmp/$f \
    http://127.0.0.1:8082/remote.php/dav/files/wetrun/$f
done
python3 -c "
import hashlib, json
print(json.dumps({'user': 'wetrun', 'files': {f: hashlib.sha1(open('/tmp/' + f, 'rb').read()).hexdigest()
      for f in ('photo.jpg', 'note.txt', 'report.pdf')}}))" > refs.json

APP=$(docker compose -p ncvol-prod ps -q app); DB=$(docker compose -p ncvol-prod ps -q db)
docker exec "$APP" su -s /bin/sh www-data -c 'php occ maintenance:mode --on'
docker exec "$DB" sh -c 'mariadb-dump -u root -p"$MARIADB_ROOT_PASSWORD" --single-transaction nextcloud' \
  > backup/nextcloud.sql
# 볼륨 백업: 흔한 방식대로 볼륨을 임시 컨테이너에 읽기 전용으로 붙여 restic으로 백업한다
R="docker run --rm -v ncvol-prod_nextcloud:/src/html:ro -v $V/backup:/src/backup:ro -v $V/restic-repo:/repo -e RESTIC_PASSWORD=nc-restic-pw restic/restic:0.18.0 -r /repo"
$R init
$R backup -q --tag nextcloud --host nextcloud /src/html /src/backup
docker exec "$APP" su -s /bin/sh www-data -c 'php occ maintenance:mode --off'
docker run --rm -v "$V/restic-repo:/repo" alpine:3 chown -R "$(id -u):$(id -g)" /repo
printf 'RESTIC_PASSWORD=nc-restic-pw\nNEXTCLOUD_ADMIN_PASSWORD=nc-admin-pw\n' > secrets.env
chmod 600 secrets.env
echo "준비 끝: set -a; . ./secrets.env; set +a; wetrun run workflow.yaml"
