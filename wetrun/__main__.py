"""wetrun CLI 진입점."""

import argparse
import fcntl
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import yaml

from wetrun import notify, report, runner, schedule
from wetrun.contract import EXIT_ERROR, EXIT_PASS, exit_code
from wetrun.isolation import IsolationError, ensure_private_dir
from wetrun.progress import Progress
from wetrun.steps import ref_files
from wetrun.workflow import WorkflowError, empty_env_refs, load

COMMANDS = {
    "run": "워크플로 실행",
    "check-input": "실행 전 입력·지원 조건 검사",
    "schedule": "예약 실행 설정 생성",
    "refs": "운영 서비스에서 정답지(refs.json) 만들기",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="wetrun", description="백업으로 서비스를 실제로 복구해 보고 동작을 검사한다."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    commands = {}
    for name, help_text in COMMANDS.items():
        commands[name] = sub.add_parser(name, help=help_text)
        commands[name].add_argument("workflow", help="워크플로 YAML 경로")
    commands["schedule"].add_argument("--at", default="03:30", help="매일 실행할 시각 HH:MM")
    commands["schedule"].add_argument(
        "--env-file", type=Path, help="비밀 값(KEY=VALUE) 파일. 본인만 읽을 수 있어야 함"
    )
    refs = commands["refs"]
    refs.add_argument("--url", required=True, help="운영 서비스 주소. 예: http://localhost:2283")
    refs.add_argument("-o", "--output", type=Path, help="저장할 곳. 기본: 워크플로의 refs")
    refs.add_argument("--force", action="store_true", help="이미 있는 정답지를 덮어씀")
    refs.add_argument("--timeout", type=float, default=3600, help="원본을 모두 받는 데 쓸 시간(초)")
    args = parser.parse_args(argv)
    if args.command == "check-input":
        return check_input(Path(args.workflow))
    if args.command == "run":
        return run(Path(args.workflow))
    if args.command == "refs":
        return refs_command(Path(args.workflow), args.url, args.output, args.force, args.timeout)
    return schedule_command(Path(args.workflow), args.at, args.env_file)


def refs_command(path: Path, url: str, out: Path | None, force: bool, timeout: float) -> int:
    """운영 서비스에서 정답지를 만든다. 검사(ref_files 단계)와 같은 설정으로 로그인·조회한다.

    워크플로 전체를 검사하지 않고 ref_files 단계만 읽는다. 처음 만들 때는 refs 파일이 아직
    없어서 check-input을 통과하지 못하기 때문이다.
    """
    try:
        wf = yaml.safe_load(path.read_text(encoding="utf-8"))
        step = next(s for s in wf["steps"] if isinstance(s, dict) and s.get("use") == "ref_files")
    except (OSError, yaml.YAMLError, TypeError, KeyError, StopIteration):
        return _refs_error(f"{path}: ref_files 단계를 찾지 못함")
    empty = sorted(empty_env_refs(step))
    if empty:
        return _refs_error("환경 변수가 비어 있음: " + ", ".join(empty))
    if out is None:
        if not isinstance(wf.get("refs"), str):
            return _refs_error("워크플로에 refs가 없음. -o로 저장할 곳을 지정하세요")
        out = path.parent / wf["refs"]

    step = {**_env_values(step), "url": url}
    try:
        refs, skipped = ref_files.make_refs(step, time.monotonic() + timeout)
    except (ref_files.ServiceError, ref_files.ConfigError) as e:
        return _refs_error(str(e))
    except ref_files.OutOfTime:
        return _refs_error(f"{timeout:.0f}초 안에 끝내지 못함. --timeout을 늘리세요")
    if skipped:
        print(
            f"wetrun refs: 원본이 서비스 기록과 다르거나 받지 못한 파일 {len(skipped)}개는 "
            f"넣지 않음{ref_files._names(skipped)}. 운영 데이터부터 확인하세요",
            file=sys.stderr,
        )
    if not refs["assets"]:
        return _refs_error("기준으로 쓸 파일이 하나도 없음")

    # 정답지는 지워지면 되살리기 어렵다. --force 없이는 덮어쓰지 않는다
    if out.exists() and not force:
        return _refs_error(f"{out}: 이미 있음. 덮어쓰려면 --force")
    # 다 쓴 뒤 한 번에 바꾼다. 백업 스크립트에서 매번 돌다가 중간에 끊겨도 지난 정답지가 남는다
    tmp = out.with_name(f".{out.name}.tmp")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(refs, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, out)
    except OSError as e:
        return _refs_error(f"{out}: 저장하지 못함 ({e.strerror or type(e).__name__})")
    albums = f", 앨범 {len(refs['albums'])}개" if "albums" in refs else ""
    print(f"wetrun refs: 파일 {len(refs['assets'])}개{albums} → {out}")
    return EXIT_PASS


def _refs_error(message: str) -> int:
    print(f"wetrun refs: {message}", file=sys.stderr)
    return EXIT_ERROR


def _env_values(obj):
    """`env:<변수>`를 실제 값으로 바꾼다."""
    if isinstance(obj, dict):
        return {k: _env_values(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_env_values(v) for v in obj]
    if isinstance(obj, str) and obj.startswith("env:"):
        return os.environ[obj[4:]]
    return obj


def schedule_command(path: Path, at: str, env_file: Path | None) -> int:
    try:
        line = schedule.cron_line(path, at, env_file, report_dir().parent)
    except schedule.ScheduleError as e:
        print(f"wetrun schedule: {e}", file=sys.stderr)
        return EXIT_ERROR
    print("# crontab -e 로 아래 줄을 붙여 넣는다")
    print(line)
    return EXIT_PASS


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
        lock = _lock(path)
    except (IsolationError, OSError) as e:
        print(f"wetrun run: 잠금 파일을 만들 수 없음: {e}", file=sys.stderr)
        return EXIT_ERROR
    if lock is None:
        print(f"wetrun run: 같은 워크플로가 이미 실행 중: {path}", file=sys.stderr)
        return EXIT_ERROR
    with lock:
        return _run(path)


def _lock(path: Path):
    """워크플로별 잠금. 예약 실행이 겹치거나 손으로 동시에 돌려도 하나만 실행한다.

    프로세스가 죽으면 운영체제가 잠금을 푼다. 잡지 못하면 None.
    """
    key = runner.workflow_id(path)
    # 리포트 폴더에 문제가 있어도 잠금은 되도록 임시 폴더에 둔다. 사용자마다 따로
    lock_dir = Path(tempfile.gettempdir()) / f"wetrun-locks-{os.getuid()}"
    lock_dir.mkdir(mode=0o700, exist_ok=True)
    ensure_private_dir(lock_dir)  # 다른 사용자가 먼저 만든 폴더면 IsolationError
    # 링크를 따라가지 않고, 내용도 지우지 않는다 (남의 파일을 덮어쓰지 않게)
    fd = os.open(lock_dir / f"{key}.lock", os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    f = os.fdopen(fd, "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        f.close()
        return None
    return f


def _run(path: Path) -> int:
    try:
        history = report.load_history(report_dir(), runner.workflow_id(path))
        progress = Progress()
        result = runner.run(path, history, progress)
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
    # 터미널이면 진행 표시가 단계 표를 이미 보여 줬다
    head = "\n" if progress.live else ""  # 진행 줄과 결과 사이를 한 줄 띄운다
    print(head + report.summary(result, secrets, steps=not progress.live))
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
