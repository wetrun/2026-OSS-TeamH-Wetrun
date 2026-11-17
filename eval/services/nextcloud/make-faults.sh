#!/bin/sh
# Nextcloud 고장 백업 4개. 파일이 www-data 소유라 root(restic 컨테이너)로 만든다
set -e
N=$(cd "$(dirname "$0")" && pwd); F=$N/faults
docker run --rm -v $N:/n alpine:3 rm -rf /n/faults >/dev/null 2>&1 || true
mkdir -p $F/work; cp -R $N/restic-repo $F/repo
docker run --rm --entrypoint sh -v $F/repo:/repo -v $F/work:/src -e RESTIC_PASSWORD=nc-restic-pw restic/restic:0.18.0 -c "
set -e
restic -r /repo restore latest --tag nextcloud --target / -q
B() { restic -r /repo backup -q --tag \$1 --host nextcloud /src/html /src/backup; }
P=/src/html/data/wetrun/files/photo.jpg; D=/src/backup/nextcloud.sql
cp \$P /tmp/p; rm \$P; B missing-file; cp /tmp/p \$P
printf X | dd of=\$P bs=1 seek=100 conv=notrunc 2>/dev/null; B corrupt-file; cp /tmp/p \$P
cp \$D /tmp/d; L=\$(wc -l < \$D); sed -i \"\$((L/2))a THIS IS NOT SQL;\" \$D; B broken-dump; cp /tmp/d \$D
rm \$D; B missing-dump; cp /tmp/d \$D
restic -r /repo snapshots --compact | tail -6"
docker run --rm -v $F:/f alpine:3 sh -c "chown -R 1000:1000 /f/repo && rm -rf /f/work"
set -a; . $N/secrets.env; set +a
for tag in missing-file corrupt-file broken-dump missing-dump; do
  sed -e "s|path: restic-repo|path: $F/repo|" -e "s|{tag: nextcloud}|{tag: $tag}|" -e "s|files: \[compose.yml\]|files: [$N/compose.yml]|" -e "s|env_file: .env|env_file: $N/.env|" -e "s|refs: refs.json|refs: $N/refs.json|" $N/workflow.yaml > $F/wf-$tag.yaml
  echo "== $tag: $(timeout 600 wetrun run $F/wf-$tag.yaml 2>&1 | grep -E "^\s+(fail|error)|결과" | tr -s " " | tr "\n" " ")"
done
echo "남은 컨테이너: $(docker ps -a --filter label=wetrun.project -q | wc -l)"
echo DONE
