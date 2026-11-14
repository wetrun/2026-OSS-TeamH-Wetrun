"""wetrun CLI 진입점."""

import argparse
import os
import sys
from pathlib import Path

from wetrun import notify, report, runner
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
    wf = load(path)  # 실행 전에 이미 통과한 워크플로. 비밀 값과 알림 설정을 읽는다
    secrets = runner.secrets(wf)
    saved = None
    try:
        saved = report.save(result, report_dir(), secrets)
    except OSError as e:
        # 저장 실패로 죽으면 파이썬이 종료 코드 1(fail)을 낸다. 판정은 그대로 두고 알리기만 한다
        print(
            f"wetrun run: 리포트를 저장하지 못함 ({e.strerror or type(e).__name__})",
            file=sys.stderr,
        )
    print(report.summary(result, secrets))
    if saved:
        print(f"리포트: {saved}")
    if "notify" in wf:
        n = wf["notify"]
        _, reason = notify.send(
            os.environ.get(n["discord"][4:], ""),  # check-input이 env:만 허용한다
            result,
            n.get("when", notify.DEFAULT_WHEN),
            secrets,
            title=service_name(path),
            report_path=str(saved.resolve()) if saved else "",
        )
        print(f"알림: {reason}", file=sys.stderr)
    return exit_code(result)


def report_dir() -> Path:
    """리포트 저장 위치. 예약 실행에서도 같은 곳에 쌓이도록 고정 위치를 쓴다."""
    return Path(os.environ.get("WETRUN_REPORT_DIR", Path.home() / ".local/share/wetrun/runs"))


def service_name(path: Path) -> str:
    """알림 첫 줄에 쓸 이름. profiles/<서비스>/workflow.yaml이면 폴더 이름, 아니면 파일 이름."""
    return path.resolve().parent.name if path.stem == "workflow" else path.stem


if __name__ == "__main__":
    sys.exit(main())
