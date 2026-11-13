"""내장 검사 공통 입출력: step.json 읽기, result.json 쓰기, 종료 코드.

모든 내장 검사는 처음(설정 읽기)과 끝(결과 쓰기·종료)이 같다. 그 부분을 여기에 모아서
검사 파일은 "무엇을 확인하나"만 짠다. 검사 컨테이너에서 돌므로 표준 라이브러리만 쓴다.

검사 파일은 이렇게 쓴다:

    def check(step: dict) -> tuple[Status, str, dict]:
        ...
        return Status.PASS, "설명", {"근거": "값"}

    if __name__ == "__main__":
        sys.exit(run(check))
"""

import json
import os
import time
from collections.abc import Callable
from pathlib import Path

from wetrun.contract import Status

# 계약: 결과 상태 → 검사 종료 코드. 이 표에 없는 상태(skipped 등)는 error로 끝낸다.
EXIT_CODES = {Status.PASS: 0, Status.FAIL: 1, Status.ERROR: 2}

DEFAULT_TIMEOUT_S = 300  # 계약의 단계 공통 키 timeout 기본값

Check = Callable[[dict], tuple[Status, str, dict]]


def io_dir() -> Path:
    """실행기가 마운트하는 폴더. 실행기는 /wetrun을 쓰고, 테스트는 WETRUN_DIR로 바꾼다."""
    return Path(os.environ.get("WETRUN_DIR", "/wetrun"))


def load_step() -> dict:
    """이 단계의 YAML 설정. env: 참조는 실행기가 실제 값으로 바꿔서 넣어 준다."""
    return _load_json(io_dir() / "step.json")


def load_refs() -> dict:
    """기준 데이터(정답지)."""
    return _load_json(io_dir() / "refs.json")


def deadline(step: dict) -> float:
    """검사가 스스로 멈출 시각 (time.monotonic 기준). 시작부터 timeout초 뒤.

    실행기는 timeout + 30초에 끊으므로, 마감에 멈춰도 결과를 쓸 여유가 있다.
    time.time()은 컴퓨터 시계를 맞추면 앞뒤로 튈 수 있다. monotonic은 앞으로만 간다.
    """
    timeout = float(step.get("timeout", DEFAULT_TIMEOUT_S))
    return time.monotonic() + max(timeout, 0)


def write_result(status: Status, message: str, evidence: dict) -> None:
    out = io_dir() / "out"
    out.mkdir(parents=True, exist_ok=True)
    result = {"status": str(status), "message": message, "evidence": evidence}
    (out / "result.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")


def run(check: Check) -> int:
    """검사를 실행하고 결과를 쓴 뒤 종료 코드를 돌려준다.

    0(pass)이 나오는 길은 check가 명시적으로 PASS를 돌려줄 때 하나뿐이다.
    예외가 나면 error(2)로 끝낸다. 그냥 두면 파이썬이 종료 코드 1을 내서
    "실행하다 죽은 검사"가 "백업이 망가짐(fail)"으로 잘못 기록된다.
    """
    try:
        status, message, evidence = check(load_step())
    except Exception as err:
        # 예외 메시지에는 URL·응답 본문 등 비밀 값이 섞일 수 있어 종류 이름만 남긴다.
        status, message, evidence = Status.ERROR, f"검사 중 예외: {type(err).__name__}", {}

    if status not in EXIT_CODES:
        message = f"검사가 알 수 없는 상태를 돌려줌: {status}"
        status, evidence = Status.ERROR, {}

    try:
        write_result(status, message, evidence)
    except Exception:
        # evidence에 JSON으로 못 바꾸는 값이 있거나 폴더에 못 쓰는 경우
        try:
            write_result(Status.ERROR, "결과를 쓰지 못함", {})
        except Exception:
            pass
        return EXIT_CODES[Status.ERROR]
    return EXIT_CODES[status]


def _load_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.name}은 JSON 객체여야 한다")
    return data
