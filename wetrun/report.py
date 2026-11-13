"""실행 결과(RunResult)를 리포트로 만든다.

- to_dict(result): JSON 리포트. 전체 판정과 종료 코드를 계산해 넣는다
- summary(result): 사람이 읽는 요약. 단계마다 상태와 메시지만 (stderr 같은 evidence는 JSON에만)
- next_actions(data): 판정을 보고 운영자가 할 일. 통과면 빈 목록
- save(result, directory): JSON 리포트를 <directory>/<run_id>.json으로 저장한다 (0600)

비밀 값은 실행기가 단계 결과에서 이미 ***로 가린다. secrets를 넘기면 한 번 더 가린다.
가리는 곳은 비밀 값이 섞일 수 있는 글자뿐이다: 단계 메시지, evidence 안의 글자, 정리 오류.
판정·상태·숫자처럼 정해진 칸은 건드리지 않는다 (비밀번호가 "pass"나 숫자여도 깨지지 않게).
"""

import json
import os
from collections.abc import Iterable
from dataclasses import asdict
from pathlib import Path

from wetrun.contract import RunResult, exit_code, verdict

REPORT_VERSION = 1
MASK = "***"
MAX_MESSAGE = 200  # 요약에서 단계 메시지를 이 길이로 자른다
# 판정 → 운영자가 알아야 할 뜻 (계약 2절: fail은 백업·복구 문제, error는 검사를 끝까지 못 함)
MEANING = {
    "fail": "백업이나 복구한 데이터에 문제가 있음",
    "error": "검사를 끝까지 하지 못함 (환경·설정 문제이고, 백업이 망가졌다는 뜻은 아님)",
}


def to_dict(result: RunResult, secrets: Iterable[str] = ()) -> dict:
    data = {
        "report_version": REPORT_VERSION,
        "verdict": str(verdict(result.steps)),
        "exit_code": exit_code(result),
        **asdict(result),
    }
    for step in data["steps"]:
        step["status"] = str(step["status"])
    return _mask(data, secrets)


def summary(result: RunResult, secrets: Iterable[str] = ()) -> str:
    data = to_dict(result, secrets)
    lines = [
        f"Wetrun 결과: {data['verdict'].upper()} (종료 코드 {data['exit_code']})",
        *[f"할 일: {a}" for a in next_actions(data)],
        f"실행 {data['run_id']} · 스냅샷 {(data['snapshot_id'] or '-')[:8]} · "
        f"{data['duration_s']}초",
        "",
    ]
    width = max((len(s["name"]) for s in data["steps"]), default=0)
    for s in data["steps"]:
        optional = "" if s["required"] else " (선택)"
        head = f"  {s['status']:<7}  {s['name']:<{width}}  {s['duration_s']:>6.1f}초"
        lines.append(f"{head}  {one_line(s['message'])}{optional}".rstrip())
    if data["cleanup_errors"]:
        lines += ["", f"정리 오류 {len(data['cleanup_errors'])}개 (남은 자원을 직접 치워야 함):"]
        lines += [f"  - {one_line(e)}" for e in data["cleanup_errors"]]
    return "\n".join(lines)


def next_actions(data: dict) -> list[str]:
    """to_dict() 결과를 보고 할 일을 한 줄씩. 정리 실패가 먼저다 (종료 코드 3이 판정보다 우선)."""
    actions = []
    if data["cleanup_errors"]:
        actions.append("남은 자원을 직접 지워야 함 (아래 정리 오류)")
    v = data["verdict"]
    if v in MEANING:
        first = next((s for s in data["steps"] if s["required"] and s["status"] == v), None)
        if first:
            actions.append(f"{MEANING[v]}. {first['name']} 단계를 확인 (근거는 JSON 리포트)")
        else:  # 필수 단계가 하나도 없음 (contract.verdict)
            actions.append(f"{MEANING[v]}. 필수 단계가 없음")
    return actions


def save(result: RunResult, directory: Path, secrets: Iterable[str] = ()) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{result.run_id}.json"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(to_dict(result, secrets), f, ensure_ascii=False, indent=2)
        f.write("\n")
    return path


def one_line(text: str) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= MAX_MESSAGE else text[: MAX_MESSAGE - 1] + "…"


def _mask(data: dict, secrets: Iterable[str]) -> dict:
    # 긴 것부터 바꿔야 한 비밀 값이 다른 비밀 값의 일부일 때도 남김없이 가려진다
    secrets = sorted({s for s in secrets if s}, key=len, reverse=True)
    if not secrets:
        return data
    for step in data["steps"]:
        step["message"] = _mask_text(step["message"], secrets)
        step["evidence"] = _mask_text(step["evidence"], secrets)
    data["cleanup_errors"] = _mask_text(data["cleanup_errors"], secrets)
    return data


def _mask_text(value, secrets: list[str]):
    """글자(str)만 골라 가린다. 목록·매핑은 안으로 들어가고, 숫자·참거짓은 그대로 둔다."""
    if isinstance(value, str):
        for s in secrets:
            value = value.replace(s, MASK)
        return value
    if isinstance(value, dict):
        return {_mask_text(k, secrets): _mask_text(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask_text(v, secrets) for v in value]
    return value
