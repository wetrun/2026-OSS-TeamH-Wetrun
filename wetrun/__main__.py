"""wetrun CLI 진입점."""

import argparse
import sys

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
    print(f"wetrun {args.command}: 아직 구현되지 않음", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
