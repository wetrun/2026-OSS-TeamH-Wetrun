"""wetrun CLI 진입점."""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from wetrun import runner
from wetrun.contract import EXIT_ERROR, EXIT_PASS, exit_code
from wetrun.isolation import IsolationError
from wetrun.workflow import WorkflowError, load

COMMANDS = {
    "run": "워크플로 실행",
    "check-input": "실행 전 입력·지원 조건 검사",
    "schedule": "예약 실행 설정 생성",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="wetrun", description="백업으로 서비스를 실제로 복구해 보고 동작을 검사한다."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text in COMMANDS.items():
        sub.add_parser(name, help=help_text).add_argument("workflow", help="워크플로 YAML 경로")
    args = parser.parse_args(argv)
    if args.command == "check-input":
        return check_input(Path(args.workflow))
    if args.command == "run":
        return run(Path(args.workflow))
    print(f"wetrun {args.command}: 아직 구현되지 않음", file=sys.stderr)
    return 2


def check_input(path: Path) -> int:
    try:
        load(path)
    except WorkflowError as e:
        print(f"wetrun check-input: {path}: 문제 {len(e.problems)}개", file=sys.stderr)
        for p in e.problems:
            print(f"- {p}", file=sys.stderr)
        return EXIT_ERROR
    print(f"wetrun check-input: {path}: 통과")
    return EXIT_PASS


def run(path: Path) -> int:
    try:
        result = runner.run(path)
    except WorkflowError:
        return check_input(path)
    except IsolationError as e:
        print(f"wetrun run: {e}", file=sys.stderr)
        return EXIT_ERROR
    # ponytail: report.py(검사·출력 담당)가 생기기 전까지 RunResult를 JSON 그대로 출력한다
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    return exit_code(result)


if __name__ == "__main__":
    sys.exit(main())
