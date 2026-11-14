"""ref_files: 복구한 서비스에 로그인해 사진(파일)이 기준 데이터(refs.json)와 같은지 확인한다.

순서:
    1. 로그인해 토큰을 받는다
    2. 목록 대조: 기준 파일이 모두 있는지, 앨범의 파일 수가 줄지 않았는지
    3. 체크섬 대조: 서비스가 기록한 체크섬과 기준 SHA-1을 전부 비교 (DB 기록 확인)
    4. 다운로드 대조: 원본을 받아 SHA-1을 계산해 비교 (실제 파일 확인).
       무작위 순서로 timeout까지 최대한 많이 받는다.
       어디서 멈춰도 그때까지 본 파일이 무작위 샘플이다.
       - 전부 봄                                  → "전부 확인"
       - 3의 법칙이 요구하는 수 이상 봄 (1%면 299) → "손상 1% 미만 (95% 신뢰도)"
       - 그보다 적게 보고 시간이 끝남             → error (timeout을 늘리거나 목표를 낮추라고 안내)
       하나라도 다르면 fail이고 비율은 추정하지 않는다

서비스 고유의 API 경로와 응답 필드 이름은 이 파일에 쓰지 않는다. 워크플로가 step.json으로 알려 준다.

step.json 키:
    url              (필수) 서비스 주소. 예: http://<서비스>:<포트>
    account          (필수) 로그인 요청 본문 그대로. 예: {email: ..., password: env:...}
    login            (필수) {path: 로그인 경로, token: 응답에서 토큰이 있는 필드}
    assets           (필수) 파일 목록 조회. {path, items, name, checksum} 필수,
                     {method, body, id, encoding, page, next} 선택 (아래 _ASSET_DEFAULTS)
    download         (필수) 원본 다운로드 경로. {id}가 파일 id로 바뀐다
    albums           앨범 목록. {path, name, count}
    max_defect_rate  다 못 볼 때 최소한 잡고 싶은 손상 비율. 기본 0.01 (1%)
    confidence       신뢰도. 기본 0.95
    seed             다운로드 순서를 정하는 시드. 없으면 무작위로 정하고 evidence에 남긴다
    timeout          단계 공통 키. 다운로드는 이 시간 안에서 최대한 많이 한다

refs.json 키: assets[{filename, sha1}], albums[{name, asset_count}]

판정:
    모두 일치                                         → pass
    로그인 거부, 파일 빠짐, 체크섬·다운로드 해시 다름, 앨범 파일 줄어듦,
    서비스가 응답하지 않거나 오류 응답                → fail
    설정 오류, 응답에 설정한 필드가 없음, 예외,
    불일치 없이 3의 법칙이 요구하는 수만큼 못 봄     → error

기준보다 파일이 많은 것은 실패가 아니다 (백업이 기준 데이터보다 나중일 수 있다). 개수만 남긴다.
"""

import base64
import binascii
import hashlib
import json
import math
import random
import sys
import time
import urllib.error
import urllib.request

from wetrun.contract import Status
from wetrun.steps._common import deadline, load_refs, run

REQUIRED_KEYS = {"url", "account", "login", "assets", "download"}
OPTIONAL_KEYS = {"albums", "max_defect_rate", "confidence", "seed"}

_ASSET_DEFAULTS = {
    "method": None,  # body가 있으면 POST, 없으면 GET
    "body": None,
    "id": "id",
    "encoding": "hex",  # 서비스가 체크섬을 적는 방식: hex 또는 base64
    "page": None,  # 다음 쪽을 요청할 때 body에 넣을 필드
    "next": None,  # 응답에서 다음 쪽 번호가 있는 필드. 비어 있으면 마지막 쪽
}
REQUEST_TIMEOUT_S = 30
CHUNK = 64 * 1024  # 다운로드를 이만큼씩 읽어 해시에 넣는다 (메모리에 통째로 올리지 않음)
MAX_LISTED = 20  # evidence에 남길 파일 이름 최대 개수
MAX_NAMED = 3  # 메시지에 적을 파일 이름 최대 개수 (알림·요약에서 JSON을 열지 않아도 보이게)
MAX_PAGES = 1000

_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class ServiceError(Exception):
    """서비스가 응답하지 않거나 오류 응답을 줌 → fail"""


class ConfigError(Exception):
    """설정이 틀렸거나 응답에 설정한 필드가 없음 → error"""


class OutOfTime(Exception):
    """마감까지 확인을 끝내지 못함"""


# ---- 3의 법칙 ----


def sample_size(max_defect_rate: float, confidence: float = 0.95) -> int:
    """손상 비율 max_defect_rate를 confidence로 잡기 위한 샘플 수. 1%, 95% → 299"""
    return math.ceil(math.log(1 - confidence) / math.log(1 - max_defect_rate))


def upper_bound(n: int, confidence: float = 0.95) -> float:
    """n개가 전부 통과했을 때 손상 비율의 상한"""
    return 1 - (1 - confidence) ** (1 / n)


def shuffled(items: list, seed: int) -> list:
    """다운로드할 순서. 같은 시드면 같은 순서다."""
    return random.Random(seed).sample(items, len(items))


# ---- 검사 ----


def check(step: dict) -> tuple[Status, str, dict]:
    try:
        cfg = _config(step)
        refs = load_refs()
        ref_files = refs.get("assets")
        if not isinstance(ref_files, list) or not ref_files:
            raise ConfigError("refs.json에 assets가 없음")
        return _verify(cfg, ref_files, refs.get("albums") or [], deadline(step))
    except ConfigError as err:
        return Status.ERROR, str(err), {}


def _verify(cfg: dict, ref_files: list, ref_albums: list, end: float) -> tuple[Status, str, dict]:
    api = _Api(cfg["url"], end)
    evidence: dict = {"expected": len(ref_files)}
    problems: list[str] = []
    try:
        # 1. 로그인
        status, body = api.json("POST", cfg["login"]["path"], cfg["account"])
        if status in (400, 401, 403):
            return Status.FAIL, f"로그인 거부 (HTTP {status})", {"login_status": status}
        _expect_ok(status, "로그인")
        api.token = _get(body, cfg["login"]["token"], "login.token")

        # 2. 목록 대조 (파일 이름), 3. 체크섬 대조 (기준 SHA-1이 서비스 기록에 있나)
        found = _list_assets(api, cfg["assets"])
        by_sha1 = {}
        names = set()
        for item in found:
            names.add(item["name"])
            by_sha1.setdefault(item["sha1"], item)
        evidence["found"] = len(found)

        missing = [r["filename"] for r in ref_files if r["filename"] not in names]
        changed = [
            r["filename"]
            for r in ref_files
            if r["filename"] in names and r["sha1"].lower() not in by_sha1
        ]
        if missing:
            evidence["missing"] = missing[:MAX_LISTED]
            problems.append(f"빠진 파일 {len(missing)}개{_names(missing)}")
        if changed:
            evidence["checksum_mismatch"] = changed[:MAX_LISTED]
            problems.append(f"체크섬이 다른 파일 {len(changed)}개{_names(changed)}")

        if cfg["albums"]:
            album_problems = _check_albums(api, cfg["albums"], ref_albums)
            evidence["albums"] = album_problems or "ok"
            if album_problems:
                problems.append(f"앨범 문제 {len(album_problems)}개")

        # 4. 다운로드 대조 (체크섬이 맞는 파일만. 안 맞는 파일은 이미 실패로 잡았다)
        matched = sorted(
            ((r, by_sha1[r["sha1"].lower()]) for r in ref_files if r["sha1"].lower() in by_sha1),
            key=lambda pair: pair[0]["filename"],
        )
        download = _download(api, cfg, matched)
        evidence["download"] = download
        if download.get("mismatch"):
            bad = download["mismatch"]
            problems.append(f"다운로드한 원본이 다른 파일 {download['mismatched']}개{_names(bad)}")

    except ServiceError as err:
        problems.append(str(err))
        return Status.FAIL, ", ".join(problems), evidence
    except OutOfTime:
        if problems:
            return Status.FAIL, ", ".join(problems) + " (timeout 전까지 확인한 것)", evidence
        return Status.ERROR, "timeout 안에 확인을 끝내지 못함", evidence

    if problems:
        return Status.FAIL, ", ".join(problems), evidence
    n, total, needed = download["checked"], download["of"], download["needed"]
    if n == total:
        return Status.PASS, f"파일 {n}개 전부 확인, 모두 원본과 일치", evidence
    rate, confidence = cfg["max_defect_rate"], cfg["confidence"]
    if n >= needed:
        return (
            Status.PASS,
            f"원본 {total}개 중 {n}개를 무작위로 확인, 모두 일치. 손상 파일은 "
            f"{download['bound']:.1%} 미만 ({confidence:.0%} 신뢰도, 시드 {download['seed']})",
            evidence,
        )
    return (
        Status.ERROR,
        f"timeout 안에 원본 {n}개만 확인 (모두 일치). 손상 {rate:.1%}를 잡으려면 {needed}개가 "
        f"필요함. timeout을 늘리거나 max_defect_rate를 키우세요",
        evidence,
    )


def _download(api: "_Api", cfg: dict, matched: list) -> dict:
    """무작위 순서로 마감까지 받아 본다. 다른 파일이 있어도 끝까지 보고, 시간이 끝나면 멈춘다."""
    needed = sample_size(cfg["max_defect_rate"], cfg["confidence"])
    result = {"checked": 0, "of": len(matched), "needed": min(needed, len(matched))}
    bad = []
    for ref, item in shuffled(matched, cfg["seed"]):
        try:
            actual = api.sha1(cfg["download"].replace("{id}", str(item["id"])))
        except OutOfTime:
            break
        except (
            ServiceError
        ) as err:  # 기록은 있는데 원본을 못 받음 (파일 누락 등). 어느 파일인지 붙인다
            raise ServiceError(f"{err}: {ref['filename']}") from None
        result["checked"] += 1
        if actual != ref["sha1"].lower():
            bad.append(ref["filename"])
    if bad:
        result["mismatch"] = bad[:MAX_LISTED]
        result["mismatched"] = len(bad)
    if result["checked"] < len(matched):
        result["seed"] = cfg["seed"]
        if result["checked"]:
            result["bound"] = round(upper_bound(result["checked"], cfg["confidence"]), 4)
    return result


def _list_assets(api: "_Api", spec: dict) -> list[dict]:
    """목록을 (쪽이 있으면 끝까지) 받아 {id, name, sha1} 목록으로 바꾼다."""
    body = dict(spec["body"]) if isinstance(spec["body"], dict) else spec["body"]
    method = spec["method"] or ("POST" if body is not None else "GET")
    found = []
    for _ in range(MAX_PAGES):
        status, resp = api.json(method, spec["path"], body)
        _expect_ok(status, "파일 목록 조회")
        items = _get(resp, spec["items"], "assets.items")
        if not isinstance(items, list):
            raise ConfigError("assets.items가 목록이 아님")
        for item in items:
            found.append(
                {
                    "id": _get(item, spec["id"], "assets.id"),
                    "name": _get(item, spec["name"], "assets.name"),
                    "sha1": _to_hex(_get(item, spec["checksum"], "assets.checksum"), spec),
                }
            )
        nxt = _get(resp, spec["next"], "assets.next", default=None) if spec["next"] else None
        if not nxt:
            return found
        body[spec["page"]] = int(nxt)
    raise ConfigError(f"파일 목록이 {MAX_PAGES}쪽을 넘음")


def _names(names: list[str]) -> str:
    """메시지 끝에 붙일 파일 이름. ': a.png, b.png, c.png 외 2개'"""
    shown = ", ".join(names[:MAX_NAMED])
    more = f" 외 {len(names) - MAX_NAMED}개" if len(names) > MAX_NAMED else ""
    return f": {shown}{more}" if names else ""


def _check_albums(api: "_Api", spec: dict, ref_albums: list) -> list[str]:
    status, resp = api.json("GET", spec["path"])
    _expect_ok(status, "앨범 목록 조회")
    if not isinstance(resp, list):
        raise ConfigError("albums 응답이 목록이 아님")
    counts = {
        _get(a, spec["name"], "albums.name"): _get(a, spec["count"], "albums.count") for a in resp
    }
    problems = []
    for ref in ref_albums:
        name, expected = ref["name"], ref["asset_count"]
        if name not in counts:
            problems.append(f"{name}: 없음")
        elif counts[name] < expected:
            problems.append(f"{name}: 파일 {counts[name]}개 (기준 {expected}개)")
    return problems


# ---- 설정 ----


def _config(step: dict) -> dict:
    """step.json을 확인하고 기본값을 채운다. 오류 메시지에 값은 넣지 않는다 (비밀 값일 수 있음)."""
    for key in ("account", "login", "assets"):
        if not isinstance(step.get(key), dict):
            raise ConfigError(f"{key}는 매핑이어야 함")
    if not isinstance(step.get("url"), str) or not step["url"]:
        raise ConfigError("url이 없음")
    login = step["login"]
    if not isinstance(login.get("path"), str) or not isinstance(login.get("token"), str):
        raise ConfigError("login에는 path와 token이 필요함")
    assets = {**_ASSET_DEFAULTS, **step["assets"]}
    for key in ("path", "items", "name", "checksum"):
        if not isinstance(assets.get(key), str):
            raise ConfigError(f"assets.{key}가 필요함")
    if assets["encoding"] not in ("hex", "base64"):
        raise ConfigError("assets.encoding은 hex 또는 base64")
    if assets["next"] and not (assets["page"] and isinstance(assets["body"], dict)):
        raise ConfigError("assets.next를 쓰려면 assets.page와 assets.body(매핑)가 필요함")
    if not isinstance(step.get("download"), str) or "{id}" not in step["download"]:
        raise ConfigError("download에는 {id}가 들어간 경로가 필요함")
    albums = step.get("albums")
    if albums is not None and not (
        isinstance(albums, dict)
        and all(isinstance(albums.get(k), str) for k in ("path", "name", "count"))
    ):
        raise ConfigError("albums에는 path, name, count가 필요함")

    rate = step.get("max_defect_rate", 0.01)
    confidence = step.get("confidence", 0.95)
    if not (_number(rate) and 0 < rate < 1 and _number(confidence) and 0 < confidence < 1):
        raise ConfigError("max_defect_rate와 confidence는 0과 1 사이")
    seed = step.get("seed")
    if seed is None:
        seed = random.SystemRandom().randrange(10**6)
    elif not isinstance(seed, int):
        raise ConfigError("seed는 정수")

    return {
        "url": step["url"].rstrip("/"),
        "account": step["account"],
        "login": login,
        "assets": assets,
        "download": step["download"],
        "albums": albums,
        "max_defect_rate": rate,
        "confidence": confidence,
        "seed": seed,
    }


def _number(value) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _get(data, path: str, key: str, default=KeyError):
    """'a.b.c' 경로로 값을 꺼낸다. 없으면 설정 오류로 본다."""
    for part in path.split("."):
        if isinstance(data, dict) and part in data:
            data = data[part]
        elif default is KeyError:
            raise ConfigError(f"응답에 {key}({path})가 없음")
        else:
            return default
    return data


def _to_hex(checksum, spec: dict) -> str:
    """서비스가 기록한 체크섬을 refs.json과 같은 소문자 hex로 바꾼다. 못 바꾸면 빈 문자열."""
    if not isinstance(checksum, str):
        return ""
    if spec["encoding"] == "base64":
        try:
            return base64.b64decode(checksum, validate=True).hex()
        except (binascii.Error, ValueError):
            return ""
    return checksum.lower()


def _expect_ok(status: int, what: str) -> None:
    if not 200 <= status < 300:
        raise ServiceError(f"{what} 실패 (HTTP {status})")


# ---- HTTP ----


class _Api:
    """서비스에 요청을 보낸다. 모든 요청은 마감을 넘지 않는다."""

    def __init__(self, base: str, end: float) -> None:
        self.base = base
        self.end = end
        self.token: str | None = None

    def _open(self, method: str, path: str, body=None):
        remaining = self.end - time.monotonic()
        if remaining <= 0:
            raise OutOfTime
        headers = {"Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            return _opener.open(req, timeout=min(REQUEST_TIMEOUT_S, remaining))
        except urllib.error.HTTPError as err:
            return err  # 4xx·5xx도 상태 코드로 판단한다
        except (urllib.error.URLError, OSError) as err:
            if self.end - time.monotonic() <= 0:
                raise OutOfTime from None
            # 메시지에 주소·토큰이 섞이지 않게 종류 이름만 남긴다
            reason = getattr(err, "reason", err)
            name = (
                type(reason).__name__ if isinstance(reason, BaseException) else type(err).__name__
            )
            raise ServiceError(f"서비스 응답 없음 ({name})") from None

    def json(self, method: str, path: str, body=None) -> tuple[int, object]:
        with self._open(method, path, body) as resp:
            status = resp.status if hasattr(resp, "status") else resp.code
            raw = resp.read()
        if not 200 <= status < 300:
            return status, None
        try:
            return status, json.loads(raw)
        except ValueError:
            raise ServiceError(f"JSON이 아닌 응답 ({method} {path})") from None

    def sha1(self, path: str) -> str:
        """원본을 조금씩 읽으며 SHA-1을 계산한다. 파일로 저장하지 않는다."""
        digest = hashlib.sha1()
        with self._open("GET", path) as resp:
            status = resp.status if hasattr(resp, "status") else resp.code
            _expect_ok(status, "원본 다운로드")
            while True:
                try:
                    chunk = resp.read(CHUNK)
                except OSError:  # 읽는 중 시간 초과·끊김
                    if time.monotonic() >= self.end:
                        raise OutOfTime from None
                    raise ServiceError("원본 다운로드 중 끊김") from None
                if not chunk:
                    break
                digest.update(chunk)
                if time.monotonic() > self.end:
                    raise OutOfTime
        return digest.hexdigest()


if __name__ == "__main__":
    sys.exit(run(check))
