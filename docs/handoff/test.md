# handoff: 테스트·평가 (김영모)

담당: `faults/`, `tests/`(계약·격리), `eval/`(시나리오 평가)

## 고장 백업 만드는 방법

실행기 작업 중 손으로 만들어 확인한 방법이다 (#13, #30). `faults/` 스크립트로 옮길 때 출발점으로 쓴다.

### 원칙

- **testenv 저장소를 직접 고치지 않는다.** `testenv/data/restic-repo`를 복사한 사본에 고장 스냅샷을 추가한다. 원본은 정상 백업 기준으로 남겨 둔다.
- 고장마다 **태그를 따로** 붙인다(`broken-dump` 등). 워크플로는 `snapshot.tag`만 바꿔서 같은 저장소의 다른 고장을 고른다.
- `--host testenv`를 붙인다. testenv 백업과 같게 해서, 호스트 차이가 결과에 끼지 않게 한다.
- 고장은 **하나만** 넣는다. 그래야 어느 단계가 왜 실패했는지 바로 보인다.

### 스크립트

`make env`로 testenv와 정상 백업을 만든 뒤 저장소 루트에서 실행한다. 사본은 `~/wetrun-faults/`에 생긴다.

```sh
#!/bin/sh
# testenv 저장소 사본에 고장 스냅샷 4개를 만든다
set -e
export RESTIC_PASSWORD=resticpwd                       # testenv 전용 값
F=$HOME/wetrun-faults; rm -rf "$F"; mkdir -p "$F"
cp -R testenv/data/restic-repo "$F/repo"
export RESTIC_REPOSITORY="$F/repo"

restic -q restore latest --tag testenv --target "$F/src"   # 정상 백업 내용 꺼내기
cd "$F/src"                                                # data/backup/immich.sql, data/library/...

# 1) DB 덤프 손상: 덤프 가운데에 SQL이 아닌 줄을 넣는다
cp data/backup/immich.sql /tmp/immich.sql.orig
python3 -c "
p='data/backup/immich.sql'; l=open(p,encoding='utf-8').read().split('\n')
l.insert(len(l)//2,'THIS IS NOT SQL;'); open(p,'w',encoding='utf-8').write('\n'.join(l))"
restic -q backup data --tag broken-dump --host testenv
cp /tmp/immich.sql.orig data/backup/immich.sql

# 2) DB 덤프 누락
mv data/backup/immich.sql /tmp/immich.sql.keep
restic -q backup data --tag missing-dump --host testenv
mv /tmp/immich.sql.keep data/backup/immich.sql

# 3) 사진 원본 1장 누락 (원본은 data/library/upload/<사용자>/<xx>/<yy>/<id>.png)
P=$(find data/library/upload -type f -name '*.png' | sort | head -1)
cp "$P" /tmp/photo.orig; rm "$P"
restic -q backup data --tag missing-photo --host testenv

# 4) 사진 원본 1장 손상 (1바이트만 바꾼다. 크기는 같고 해시만 달라진다)
cp /tmp/photo.orig "$P"
printf 'X' | dd of="$P" bs=1 seek=100 conv=notrunc 2>/dev/null
restic -q backup data --tag corrupt-photo --host testenv

restic snapshots --compact
```

워크플로는 `profiles/immich/workflow.yaml`을 복사해서 저장소 경로와 태그만 바꾼다. 복사본은 다른 폴더에 두므로 상대 경로(`../../testenv`)를 절대 경로로 바꿔야 한다.

```sh
T=$PWD/testenv
for tag in broken-dump missing-dump missing-photo corrupt-photo; do
  sed -e "s#\.\./\.\./testenv#$T#g" \
      -e "s#path: $T/data/restic-repo#path: $HOME/wetrun-faults/repo#" \
      -e "s#{tag: testenv, select: latest}#{tag: $tag, select: latest}#" \
      profiles/immich/workflow.yaml > "$HOME/wetrun-faults/wf-$tag.yaml"
done

export RESTIC_PASSWORD=resticpwd TESTENV_ADMIN_PASSWORD=testpwd
uv run wetrun run ~/wetrun-faults/wf-missing-photo.yaml; echo "exit=$?"
```

### 기대 결과 (Linux에서 확인, #30)

| 태그 | 판정 (종료 코드) | 실패하는 단계 | 근거 |
|---|---|---|---|
| `testenv` (정상) | `pass` (0) | - | 사진 5개 전부 원본과 일치 |
| `broken-dump` | `fail` (1) | `restore-db` (`exec`) | psql 종료 코드 3, 오류 줄 위치 |
| `missing-dump` | `fail` (1) | `restore-db` (`exec`) | 입력 파일 없음 |
| `missing-photo` | `fail` (1) | `photos` (`ref_files`) | 원본 다운로드 실패 (HTTP 404) |
| `corrupt-photo` | `fail` (1) | `photos` (`ref_files`) | 다운로드한 원본이 다른 파일 1개 |

- 사진 누락·손상은 `ready`(HTTP 200)를 통과하고 `photos`에서만 잡힌다. 서비스가 응답해도 데이터가 맞다는 뜻은 아니기 때문이다.
- 모든 실행 뒤 남은 컨테이너와 실행 디렉터리가 0개여야 한다: `docker ps -a --filter label=wetrun.project -q`

### `error`(2)가 나와야 하는 경우

#13 기준으로는 백업 문제가 아니라 환경·입력 문제다. 백업을 고칠 필요 없이 실행 조건만 바꿔서 만든다.

| 경우 | 만드는 방법 | 기대 |
|---|---|---|
| restic 비밀번호 틀림 | `RESTIC_PASSWORD=wrong` | `restore` `error` |
| 태그에 맞는 스냅샷 없음 | `snapshot.tag`를 없는 값으로 | `restore` **`fail`** (백업이 없다는 뜻으로 본다, #16) |
| 메모리 부족 | `compose.mem_limit: {immich-server: 64m}` | `up` `error` ("메모리 부족") |
| 이미지 없음 | compose의 이미지 태그를 없는 값으로 | `up` `error` |

### 주의

- **macOS:** Docker가 공유하지 않은 폴더는 빈 폴더로 마운트된다. `export WETRUN_WORKDIR=~/.cache/wetrun`처럼 홈 아래를 지정한다 ([runner.md](runner.md)).
- **메모리:** 검증용 Immich가 하나 더 뜬다. testenv Immich를 켜 둔 채로 돌리려면 그만큼 여유가 필요하다. 부족하면 `make env-down` 후 돌린다.
- **필수 설정 누락**(README 고장 시나리오): testenv 백업에는 `.env`가 들어 있지 않아 이 방법으로는 만들 수 없다. 워크플로의 `env_file`에서 `DB_PASSWORD` 같은 값을 빼는 방식이 후보다. 아직 시험하지 않았다.
