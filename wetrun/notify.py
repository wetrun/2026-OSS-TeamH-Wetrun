"""실행 결과를 Discord 웹훅으로 알린다.

- should_notify(result, when): 알릴지 정한다. 기본은 fail·error일 때. 정리 실패는 항상 알린다
- payload(result, title=, report_path=): Discord에 보낼 본문 (한 줄 글자 + 카드 하나)
- send(webhook_url, result, when, ...): 필요하면 보내고 (보냈는지, 이유)를 돌려준다

알림 모양 (시안을 실제 채널에서 비교해 정함):
- 한 줄 글자: 판정 · 서비스 — 문제 단계. 휴대폰 푸시 미리보기에 이 줄이 보인다
- 카드: 판정 색 막대(pass 초록, fail 빨강, error 주황) → 제목(해요체 한 문장) → 원인 →
  할 일 → 단계 상자(고정폭으로 줄 맞춤) → 정리 오류 → 리포트 위치 → 컴퓨터·스냅샷·총 시간
- 보내는 이름은 "Wetrun"으로 덮어쓴다. 사용자가 웹훅 이름을 바꿀 필요가 없다
- pass는 무음(SUPPRESS_NOTIFICATIONS): 채널에는 남지만 푸시는 울리지 않는다.
  "알림이 울리면 할 일이 있다"를 지키려고. 정리 실패가 섞이면 울린다

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
from pathlib import Path

from wetrun import report
from wetrun.contract import RunResult, verdict

WHEN_CHOICES = ("pass", "fail", "error")  # when에 쓸 수 있는 판정. check-input이 확인할 때 쓴다
DEFAULT_WHEN = ("fail", "error")
TIMEOUT_S = 10
USERNAME = "Wetrun"
SUPPRESS_NOTIFICATIONS = 4096  # Discord 메시지 플래그: 채널엔 올라가고 푸시는 울리지 않음
MAX_CLEANUP_LISTED = 5  # 알림에 적을 정리 오류 최대 개수 (전부는 리포트에)
MAX_STEPS_LISTED = 30  # 단계 상자에 적을 최대 줄 수
# Discord 제한: 글자 2000자, 카드 제목 256자, 설명 4096자, 칸 값 1024자, 카드 전체 6000자
LIMIT_CONTENT, LIMIT_TITLE, LIMIT_DESC, LIMIT_FIELD = 2000, 256, 4096, 1024

COLOR = {"pass": 0x57F287, "fail": 0xED4245, "error": 0xF0B232}
MARK = {"pass": "✅", "fail": "❌", "error": "⚠️", "skipped": "⏭️"}
TITLE = {
    "pass": "백업을 실제로 쓸 수 있어요",
    "fail": "백업에 문제가 있어요",
    "error": "검사를 끝내지 못했어요",
}
NOTE = {"error": "백업이 망가졌다는 뜻은 아니에요."}
TODO = {
    "fail": "백업 원본과 백업 작업을 확인해 주세요.",
    "error": "설정이나 환경을 고친 뒤 다시 실행해 주세요.",
}


def should_notify(result: RunResult, when: Iterable[str] | str = DEFAULT_WHEN) -> bool:
    if result.cleanup_errors:
        return True
    if isinstance(when, str):  # YAML에서 `when: fail`처럼 하나만 쓴 경우
        when = [when]
    return str(verdict(result.steps)) in set(when)


def payload(
    result: RunResult, secrets: Iterable[str] = (), *, title: str = "", report_path: str = ""
) -> dict:
    data = report.to_dict(result, secrets)
    v = data["verdict"]
    steps = data["steps"]
    bad = next((s for s in steps if s["required"] and s["status"] == v), None)
    cleanup = data["cleanup_errors"]

    # 한 줄 글자: 판정 · 서비스 — 문제 단계 (원인은 카드에 한 번만)
    name = f" · {title}" if title else ""
    if v == "pass":
        head = f"{len(steps)}단계 모두 통과"
    else:
        head = f"`{bad['name']}` 단계" if bad else "필수 단계 없음"
    if cleanup:
        head += " · 정리 실패"
    content = _cut(f"{MARK.get(v, '')} **{v.upper()}{name}** — {head}", LIMIT_CONTENT)

    # 카드 설명: (주의) → 원인 → 할 일
    if v == "pass":
        desc = f"> {_cut(report.one_line(steps[-1]['message']), 300)}" if steps else ""
    else:
        why = report.one_line(bad["message"]) if bad else "필수 단계가 없음"
        desc = (f"{NOTE[v]}\n" if v in NOTE else "") + f"> {_cut(why, 1000)}"
        desc += f"\n\n**할 일** {TODO.get(v, '')}"

    fields = []
    if steps:
        fields.append({"name": "단계", "value": _steps_box(steps), "inline": False})
    if data.get("warnings"):  # 판정에 영향 없는 참고 (실행 이력, contract 6절 제안)
        lines = [f"• {report.one_line(w)}" for w in data["warnings"][:MAX_CLEANUP_LISTED]]
        fields.append({"name": "참고", "value": _cut("\n".join(lines), LIMIT_FIELD)})
    if cleanup:
        lines = [f"🧹 {report.one_line(e)}" for e in cleanup[:MAX_CLEANUP_LISTED]]
        if len(cleanup) > MAX_CLEANUP_LISTED:
            lines.append(f"그 밖에 {len(cleanup) - MAX_CLEANUP_LISTED}개 (리포트에)")
        label = f"정리 오류 {len(cleanup)}개 · 남은 자원을 직접 지워야 함"
        fields.append({"name": label, "value": _cut("\n".join(lines), LIMIT_FIELD)})
    show_report = bool(report_path) and v != "pass"
    if show_report:
        fields.append({"name": "리포트", "value": _cut(f"`{_home(report_path)}`", LIMIT_FIELD)})

    # 맨 아래: 컴퓨터 · (실행 ID) · 스냅샷 · 총 시간. 리포트 칸이 있으면 실행 ID는 경로에 있다
    foot = [socket.gethostname()]
    if not show_report:
        foot.append(f"실행 {data['run_id']}")
    if data["snapshot_id"]:
        foot.append(f"스냅샷 {data['snapshot_id'][:8]}")
    foot.append(f"총 {data['duration_s']}초")

    embed = {
        "color": COLOR.get(v, 0),
        "title": _cut(TITLE.get(v, v), LIMIT_TITLE),
        "description": _cut(desc, LIMIT_DESC),
        "fields": [{**f, "inline": False} for f in fields],
        "footer": {"text": " · ".join(foot)},
    }
    if data["started_at"]:
        embed["timestamp"] = data["started_at"]  # Discord가 보는 사람의 시간대로 바꿔 보여 준다
    body = {
        "username": USERNAME,
        "content": content,
        "embeds": [embed],
        # 메시지에 @everyone 같은 글자가 섞여도 아무도 호출하지 않는다
        "allowed_mentions": {"parse": []},
    }
    if v == "pass" and not cleanup:
        body["flags"] = SUPPRESS_NOTIFICATIONS
    return body


def _steps_box(steps: list[dict]) -> str:
    """단계를 고정폭 상자(코드 블록)로. 이름과 시간이 세로로 줄 맞춰 보인다."""
    shown = steps[:MAX_STEPS_LISTED]
    width = max(len(s["name"]) for s in shown)
    rows = []
    for s in shown:
        took = "건너뜀" if s["status"] == "skipped" else f"{s['duration_s']:>5.1f}초"
        name = s["name"].replace("`", "'")  # 이름의 ```가 코드 블록을 닫아 상자가 깨지지 않게
        rows.append(f"{MARK.get(s['status'], '·')} {name.ljust(width)}  {took}")
    if len(steps) > MAX_STEPS_LISTED:
        rows.append(f"… 그 밖에 {len(steps) - MAX_STEPS_LISTED}단계")
    box = "```\n" + "\n".join(rows) + "\n```"
    while len(box) > LIMIT_FIELD and len(rows) > 1:  # 이름이 아주 긴 경우
        rows = rows[:-2] + ["… (나머지는 리포트에)"]
        box = "```\n" + "\n".join(rows) + "\n```"
    return box


def _cut(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


def _home(path: str) -> str:
    """홈 폴더를 ~로 줄인다. 휴대폰에서도 한 줄에 보이게."""
    home = str(Path.home())
    return "~" + path[len(home) :] if path.startswith(home + "/") else path


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
        body = payload(result, [*secrets, webhook_url], title=title, report_path=report_path)
        req = urllib.request.Request(
            webhook_url,
            data=json.dumps(body).encode(),
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
