"""http: 주소에 GET 요청을 보내 기대한 상태 코드가 마감 안에 오는지 확인한다.

서비스가 켜지는 중일 수 있으므로 마감까지 간격을 두고 다시 시도한다.

step.json 키:
    url            (필수) 요청할 주소. 예: http://<서비스>:<포트>/<경로>
    expect_status  기대하는 상태 코드. 기본 200 (예: 로그인 없이 막히는지 보려면 401)
    interval       다시 시도하는 간격(초). 0보다 커야 함. 기본 2
    timeout        단계 공통 키. 기본 300. 이 시간 동안 기다린다

판정:
    기대한 코드가 옴            → pass
    마감까지 다른 코드·연결 실패 → fail (마지막 응답을 evidence에 남김)
    설정 오류·예외·한 번도 못 보냄 → error

리다이렉트(3xx)는 자동으로 따라간 뒤의 상태 코드로 판정한다.
"""

import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from wetrun.contract import Status
from wetrun.steps._common import deadline, run

# 이 검사의 키 (계약 3절 "검사별 키"). check-input이 공통 키를 뺀 나머지를 이것과 비교한다.
REQUIRED_KEYS = {"url"}
OPTIONAL_KEYS = {"expect_status", "interval"}

REQUEST_TIMEOUT_S = 10  # 요청 하나가 기다리는 최대 시간

# 환경 변수의 프록시 설정(HTTP_PROXY 등)을 무시한다.
# 검사는 같은 격리 네트워크의 서비스에 직접 붙어야 하고, 프록시를 타면 바깥으로 나가려 한다.
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def check(step: dict) -> tuple[Status, str, dict]:
    url = step.get("url")
    if not isinstance(url, str) or not url:
        return Status.ERROR, "step.json에 url이 없음", {}
    expect = int(step.get("expect_status", 200))
    interval = float(step.get("interval", 2))
    if interval <= 0:
        return Status.ERROR, "interval은 0보다 커야 함", {}
    end = deadline(step)
    started = time.monotonic()

    attempts = 0
    last = None  # 마지막으로 받은 상태 코드 또는 연결 실패 종류
    while (remaining := end - time.monotonic()) > 0:
        attempts += 1
        last = probe(url, min(REQUEST_TIMEOUT_S, remaining))
        if last == expect:
            evidence = _evidence(url, expect, last, attempts, started)
            return Status.PASS, f"{expect} 응답 ({attempts}번째 시도)", evidence
        time.sleep(max(min(interval, end - time.monotonic()), 0))

    if attempts == 0:
        # 한 번도 요청하지 못했으면 확인한 게 없다. fail도 pass도 아니다.
        return Status.ERROR, "timeout이 너무 짧아 요청을 보내지 못함", {}
    evidence = _evidence(url, expect, last, attempts, started)
    return Status.FAIL, f"마감까지 {expect} 응답 없음 (마지막: {last})", evidence


def probe(url: str, timeout: float) -> int | str:
    """요청을 한 번 보내 상태 코드(int)나 연결 실패 종류(str)를 돌려준다.

    urllib는 4xx·5xx 응답을 예외(HTTPError)로 던진다. 브라우저 fetch와 다르다.
    HTTPError는 URLError의 하위 클래스라서 반드시 먼저 잡아야 한다.
    """
    try:
        with _opener.open(url, timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as err:
        err.close()
        return err.code
    except urllib.error.URLError as err:
        # err.reason이 예외(ConnectionRefusedError 등)면 그 이름, 아니면 "URLError"
        reason = err.reason
        return type(reason).__name__ if isinstance(reason, BaseException) else "URLError"
    except (TimeoutError, OSError) as err:
        return type(err).__name__


def safe_url(url: str) -> str:
    """evidence에 남길 주소. 사용자 정보(user:pass@)와 쿼리(?token=...)를 뺀다."""
    p = urllib.parse.urlsplit(url)
    host = p.hostname or ""
    if p.port:
        host = f"{host}:{p.port}"
    return urllib.parse.urlunsplit((p.scheme, host, p.path, "", ""))


def _evidence(url: str, expect: int, last: int | str | None, attempts: int, started: float) -> dict:
    return {
        "url": safe_url(url),
        "expect_status": expect,
        "last": last,
        "attempts": attempts,
        "waited_s": round(time.monotonic() - started, 1),
    }


if __name__ == "__main__":
    sys.exit(run(check))
