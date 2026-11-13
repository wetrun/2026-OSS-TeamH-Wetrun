"""실행 결과를 Discord 웹훅으로 알린다.

- should_notify(result, when): 알릴지 정한다. 기본은 fail·error일 때. 정리 실패는 항상 알린다
- message(result, title=, report_path=): Discord 본문. 휴대폰 푸시 미리보기에 첫 줄만 보여도
  알 수 있게 판정·서비스 이름을 첫 줄에, 할 일·문제 단계를 그다음에, 기록(컴퓨터·실행 ID·리포트
  위치)을 맨 아래에 둔다. 2000자를 넘으면 가운데(단계 목록)를 줄이고 맨 아래 기록은 남긴다
- send(webhook_url, result, when, ...): 필요하면 보내고 (보냈는지, 이유)를 돌려준다

서비스 이름(title)과 리포트 위치(report_path)는 notify가 알 수 없어서 부르는 쪽이 넘긴다.
둘 다 없어도 된다.

알림이 실패해도 검증 결과는 바뀌지 않아야 하므로 예외를 던지지 않는다.
웹훅 주소는 비밀 값이라 반환값·메시지 어디에도 넣지 않는다.
"""

import json
import socket
import urllib.error
import urllib.request
from collections.abc import Iterable

from wetrun import report
from wetrun.contract import RunResult, Status, verdict

DISCORD_LIMIT = 2000
WHEN_CHOICES = ("pass", "fail", "error")  # when에 쓸 수 있는 판정. check-input이 확인할 때 쓴다
DEFAULT_WHEN = ("fail", "error")
TIMEOUT_S = 10
MAX_CLEANUP_LISTED = 5  # 알림에 적을 정리 오류 최대 개수 (전부는 리포트에)
MARK = {Status.PASS: "✅", Status.FAIL: "❌", Status.ERROR: "⚠️"}


def should_notify(result: RunResult, when: Iterable[str] | str = DEFAULT_WHEN) -> bool:
    if result.cleanup_errors:
        return True
    if isinstance(when, str):  # YAML에서 `when: fail`처럼 하나만 쓴 경우
        when = [when]
    return str(verdict(result.steps)) in set(when)


def message(
    result: RunResult, secrets: Iterable[str] = (), *, title: str = "", report_path: str = ""
) -> str:
    data = report.to_dict(result, secrets)
    v = Status(data["verdict"])
    name = f" · {title}" if title else ""
    head = [
        f"{MARK.get(v, '')} **Wetrun {v.upper()}{name}** (종료 코드 {data['exit_code']})",
        *[f"할 일: {a}" for a in report.next_actions(data)],
    ]

    body = []
    for s in data["steps"]:
        if s["status"] in ("pass", "skipped"):
            continue
        optional = " (선택)" if not s["required"] else ""
        body.append(f"- {s['status']} `{s['name']}`: {report.one_line(s['message'])}{optional}")
    skipped = sum(s["status"] == "skipped" for s in data["steps"])
    if skipped:
        body.append(f"- 건너뛴 단계 {skipped}개")
    errors = data["cleanup_errors"]
    if errors:
        body.append(f"정리 오류 {len(errors)}개:")
        body += [f"- {report.one_line(e)}" for e in errors[:MAX_CLEANUP_LISTED]]
        if len(errors) > MAX_CLEANUP_LISTED:
            body.append(f"- 그 밖에 {len(errors) - MAX_CLEANUP_LISTED}개")

    tail = [
        f"`{socket.gethostname()}` · 실행 `{data['run_id']}` · "
        f"스냅샷 `{(data['snapshot_id'] or '-')[:8]}` · {data['duration_s']}초",
        f"리포트: `{report_path}`" if report_path else "자세한 내용은 리포트 JSON을 보세요.",
    ]
    return _fit(head, body, tail)


def _fit(head: list[str], body: list[str], tail: list[str]) -> str:
    """2000자 안에 맞춘다. 첫 줄(판정)과 맨 아래(어디서 볼지)는 남기고 가운데를 줄인다."""
    lines, trimmed = list(body), False
    while True:
        shown = lines + (["- … (나머지는 리포트에)"] if trimmed else [])
        text = "\n".join(head + shown + tail)
        if len(text) <= DISCORD_LIMIT or not lines:
            break
        lines.pop()  # 단계 목록을 뒤에서부터 한 줄씩 뺀다
        trimmed = True
    # 첫 줄·할 일만으로도 넘치면 (메시지가 아주 긴 경우) 그냥 자른다
    return text if len(text) <= DISCORD_LIMIT else text[: DISCORD_LIMIT - 2] + "\n…"


def send(
    webhook_url: str,
    result: RunResult,
    when: Iterable[str] | str = DEFAULT_WHEN,
    secrets: Iterable[str] = (),
    *,
    title: str = "",
    report_path: str = "",
    allow_http: bool = False,  # 테스트용 가짜 서버만
) -> tuple[bool, str]:
    if not should_notify(result, when):
        return False, "알릴 결과 아님"
    if not (webhook_url.startswith("https://") or allow_http):
        return False, "웹훅 주소는 https여야 함"
    try:
        # allowed_mentions: 메시지에 @everyone 같은 글자가 섞여도 아무도 호출하지 않는다
        payload = {
            "content": message(
                result, [*secrets, webhook_url], title=title, report_path=report_path
            ),
            "allowed_mentions": {"parse": []},
        }
        req = urllib.request.Request(
            webhook_url,
            data=json.dumps(payload).encode(),
            method="POST",
            headers={"Content-Type": "application/json", "User-Agent": "wetrun-notify"},
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return True, f"보냄 (HTTP {resp.status})"
    except urllib.error.HTTPError as err:
        err.close()
        return False, f"전송 실패 (HTTP {err.code})"
    except (urllib.error.URLError, OSError) as err:
        reason = getattr(err, "reason", err)
        name = type(reason).__name__ if isinstance(reason, BaseException) else type(err).__name__
        return False, f"전송 실패 ({name})"
    except Exception as err:  # 알림 때문에 검증 결과가 사라지면 안 된다
        return False, f"알림을 만들지 못함 ({type(err).__name__})"
