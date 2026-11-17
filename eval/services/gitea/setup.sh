#!/bin/sh
# Gitea 시험 환경: 운영 역할 Gitea + 저장소 1개(커밋 2개) + restic 백업 + 정답지(refs.json)
# 실행 위치: 이 폴더. 값은 모두 시험 전용이다. 필요: docker, git, restic, curl, python3
set -e
cd "$(dirname "$0")"
mkdir -p data
docker compose -p gitea-prod up -d
until curl -sf http://127.0.0.1:3000/api/healthz >/dev/null; do sleep 2; done
docker exec -u git gitea gitea admin user create --admin --username wetrun \
  --password wetrun-gitea-pw1 --email wetrun@test.local --must-change-password=false
TOKEN=$(docker exec -u git gitea gitea admin user generate-access-token \
  --username wetrun --token-name wetrun --scopes all --raw)
curl -sf -u wetrun:wetrun-gitea-pw1 -H "Content-Type: application/json" \
  -d '{"name":"demo","private":true}' http://127.0.0.1:3000/api/v1/user/repos >/dev/null

W=$(mktemp -d)
(cd "$W" && git init -q -b main && git config user.email t@t && git config user.name t \
  && printf '# Wetrun 시험 저장소\n' > README.md && head -c 200000 /dev/urandom > photo.bin \
  && git add -A && git commit -qm first && echo '두번째 커밋' >> README.md && git commit -qam second \
  && git push -q http://wetrun:wetrun-gitea-pw1@127.0.0.1:3000/wetrun/demo.git main)
python3 - "$W" > refs.json <<'PY'
import hashlib, json, subprocess, sys
w = sys.argv[1]
head = subprocess.check_output(["git", "-C", w, "rev-parse", "HEAD"], text=True).strip()
files = {f: hashlib.sha1(open(f"{w}/{f}", "rb").read()).hexdigest() for f in ("README.md", "photo.bin")}
print(json.dumps({"repo": "wetrun/demo", "branch": "main", "commit": head, "files": files}))
PY
rm -rf "$W"
printf 'GITEA_TOKEN=%s\nRESTIC_PASSWORD=gitea-restic-pw\n' "$TOKEN" > secrets.env
chmod 600 secrets.env

# 백업: SQLite라 서비스를 멈추고 폴더째. data/ssh는 root 소유라 일반 사용자는 못 읽는다(경고만)
export RESTIC_REPOSITORY=restic-repo RESTIC_PASSWORD=gitea-restic-pw
docker compose -p gitea-prod stop
restic -q init
restic -q backup --tag gitea --host gitea data || true
docker compose -p gitea-prod start
echo "준비 끝: set -a; . ./secrets.env; set +a; wetrun run workflow.yaml"
