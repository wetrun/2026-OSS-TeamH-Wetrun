# 데이터 크기에 따른 복구·검사 시간

파일 수가 늘어날 때 Wetrun의 단계별 시간이 어떻게 늘어나는지, 그리고 `photos`(ref_files) 단계의 기본 timeout(300초)이 충분한지 확인했다.
한 번에 크게 재는 대신 **300 → 1500 → 3000개** 세 단계로 늘려, 개수에 따라 시간이 어떻게 변하는지 보이게 했다.

- 시험일: 2026-11-17
- 환경: Windows + WSL2, Docker Desktop, CPU 16개(WSL 기준), WSL 메모리 7.6GiB, 디스크 종류: NVMe SSD(삼성 512GB). Immich v3.3.5, restic 0.18.1
- 백업 저장소: 같은 PC의 폴더(`testenv/data/restic-repo`). 원격 저장소는 쓰지 않았다
- 재현: 아래 [재현](#재현)

## 데이터

`testenv/seed_dataset.py`가 만든다 (`make seed-dataset N=...`). 휴대폰 사진·동영상의 형식과 용량을 흉내 냈다.

| 항목 | 값 |
|---|---|
| 사진 | 4032x3024(1200만 화소) JPEG, 장당 약 2.6 / 3.7 / 5.2MB (평균 약 3.8MB) |
| 동영상 | 50개 중 1개. 1080p 30fps H.264 MP4, 16Mbps, 5~15초 (10~30MB) |
| 내용 | ffmpeg 테스트 화면 + 잡음. 파일마다 잡음이 달라 restic이 중복으로 합치지 못하고, 이미 압축된 형식이라 restic 압축으로도 줄지 않는다 |
| 생성 | Immich 서버 이미지 안의 ffmpeg. Immich 버전이 같으면 누가 만들어도 같은 바이트 |
| 단계 | 데이터셋 295 / 1495 / 2995개 + `make seed`의 샘플 5장 = Immich 전체 300 / 1500 / 3000개 |

처음에는 그라데이션 PNG를 썼는데, restic에서 723MiB가 42MiB로 압축돼 복원 시간이 실제보다 빠르게 나왔다. 그래서 압축되지 않는 데이터로 바꿨다.
이번 데이터의 restic 압축률은 **1.00배(절약 0.49%)** 였다.

## 방법

1. `make env-clean YES=1` → `make env-up` → `make seed`
2. 단계마다 `make seed-dataset N=<295|1495|2995>` → `make backup` → `wetrun run profiles/immich/workflow.yaml` 3회
3. 단계 사이에는 지우지 않고 이어서 늘렸다 (이미 올린 파일은 duplicate로 건너뛴다)

워크플로는 바꾸지 않았다. `photos` 단계에는 `timeout`이 없어 기본값 300초가 적용됐다.

## 결과 [측정]

3회 평균(최소~최대), 단위 초. 9회 모두 `pass`.

| Immich 전체 | 데이터셋 용량 | 백업 크기 | restore | restore-db | photos | photos 메시지 | 전체 |
|---|---|---|---|---|---|---|---|
| 300 | 1.19 GiB | 1.35 GiB | 4.6 (4.2~5.3) | 19.7 (19.0~20.2) | 9.0 (8.1~10.6) | 300개 전부 확인, 모두 원본과 일치 | 92.1 (90.6~94.2) |
| 1500 | 6.01 GiB | 6.61 GiB | 15.0 (13.1~17.5) | 19.8 (18.6~22.0) | 25.9 (24.8~26.6) | 1500개 전부 확인, 모두 원본과 일치 | 120.9 (116.0~130.5) |
| 3000 | 12.08 GiB | 13.22 GiB | 32.4 (30.3~36.3) | 22.4 (21.4~23.3) | 54.4 (51.9~58.7) | 3000개 전부 확인, 모두 원본과 일치 | 168.2 (162.8~170.9) |

나머지 단계는 크기와 거의 상관없었다: up-db 약 11~12초, up 약 37초, ready 약 4초.
백업 크기가 데이터셋보다 약 9% 큰 것은 Immich가 만든 썸네일·미리보기·동영상 변환본과 DB 덤프 때문이다.

## 해석

- **파일 수 10배(300 → 3000)에 전체 시간은 약 1.8배(92 → 168초)** 였다. 고정 비용(DB 기동, DB 복원, 서비스 기동, 응답 확인 ≈ 70초)이 커서, 작은 라이브러리도 약 1분 30초가 걸린다.
- **개수에 비례해 느는 단계는 restore와 photos뿐**이다. restore는 1500개 이상에서 약 0.4GiB/s, photos는 약 "4초 + 파일당 17ms"(약 0.22GiB/s)였다.
- **restore-db는 거의 그대로**였다(약 20 → 22초). DB에는 파일이 아니라 파일 정보만 들어가기 때문이다.
- 단계마다 첫 실행에 "평소보다 느림" 경고가 떴다. 더 작은 데이터의 실행 이력과 비교한 것이라 정상이다.

## photos timeout 기본값(300초) 근거

- 세 단계 9회 모두 **표본이 아니라 전부 확인**했다. 3000개도 최대 59초로, 300초 안에 다 받았다.
- 299개(3의 법칙의 최소 표본)는 300개 단계에서 직접 측정된다: 300개 전부 확인에 **최대 10.6초**, 기본값의 약 3.5%다.
- 데이터셋 평균 약 4.1MiB/개이므로 299개는 약 1.21GiB다. 고정 시간 약 4초를 빼면, 300초 안에 299개를 받으려면 **다운로드 속도가 초당 약 4.2MiB 이상**이면 된다. 측정 PC(약 0.22GiB/s)보다 **약 50배 느린 환경**까지 여유가 있다.
- photos는 백업 저장소가 아니라 같은 PC에서 복구한 서비스에서, Docker 내부 네트워크로 받는다. 그래서 속도는 네트워크가 아니라 **그 컴퓨터의 디스크·CPU**가 정한다. 원격 저장소를 써도 photos 근거는 그대로다.

## 한계

- PC 1대, 로컬 백업 저장소에서만 쟀다. restore는 네트워크 전송이 없는 최선의 경우다. NAS·클라우드 저장소, HDD에서는 다를 수 있다.
- 최대 3000개(약 12GiB)까지 쟀다. 그보다 큰 라이브러리는 위 증가 추세로 추정해야 한다.
- 데이터는 합성이다. 사진 크기는 12MP JPEG 수준이지만 내용은 테스트 화면 + 잡음이고 EXIF가 없다. Immich 썸네일 처리 시간은 실제 사진과 다를 수 있다.
- 동영상 비율(개수 2%, 용량 약 8%)과 길이(5~15초)는 실제 근거 없이 정했다. 실제 라이브러리는 동영상 용량 비중이 더 클 가능성이 높다.
- `photos` 표본 검사("손상 1% 미만, 95% 신뢰도")가 실제로 동작하는 경우는 이번 측정에서 나오지 않았다. timeout을 줄여(예: 20초) 따로 확인할 수 있다.

## 재현

저장소 맨 위 폴더에서. 디스크는 약 50GB가 필요하다.

```sh
make env-clean YES=1
make env-up
make seed
export RESTIC_PASSWORD=resticpwd TESTENV_ADMIN_PASSWORD=testpwd

make seed-dataset N=295 && make backup
uv run wetrun run profiles/immich/workflow.yaml   # 3회

make seed-dataset N=1495 && make backup
uv run wetrun run profiles/immich/workflow.yaml   # 3회

make seed-dataset N=2995 && make backup
uv run wetrun run profiles/immich/workflow.yaml   # 3회
```

용량·백업 크기 확인:

```sh
du -sh testenv/dataset/v3
cd testenv && RESTIC_REPOSITORY=./data/restic-repo restic snapshots && RESTIC_REPOSITORY=./data/restic-repo restic stats --mode raw-data
```
