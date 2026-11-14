"""예약 실행용 crontab 줄을 만든다. 설치는 사용자가 한다 (`crontab -e`에 붙여 넣기).

cron은 환경이 거의 비어 있어서 세 가지를 줄 안에 넣는다.
- PATH: restic·docker를 찾도록 지금 셸의 PATH
- 비밀 값: `--env-file`의 `KEY=VALUE`를 읽어 환경 변수로 (워크플로의 env: 참조용)
- 로그: 요약·경고를 `<데이터 폴더>/cron.log`에 이어 쓴다. JSON 리포트는 따로 저장된다

중복 실행은 `wetrun run`이 워크플로별 잠금으로 막는다.
ponytail: cron만 만든다. systemd timer가 필요해지면 같은 명령으로 unit 두 개를 만들면 된다.
"""

import os
import re
import shlex
import stat
import sys
from pathlib import Path

_AT = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


class ScheduleError(Exception):
    pass


def cron_line(workflow: Path, at: str, env_file: Path | None, data_dir: Path) -> str:
    """매일 `at`(HH:MM)에 `wetrun run <workflow>`를 실행하는 crontab 줄."""
    m = _AT.match(at)
    if not m:
        raise ScheduleError(f"--at은 HH:MM 형식이어야 함: {at!r}")
    if not workflow.is_file():
        raise ScheduleError(f"워크플로가 없음: {workflow}")
    parts = [f"export PATH={shlex.quote(os.environ.get('PATH', '/usr/bin:/bin'))}"]
    if env_file is not None:
        if not env_file.is_file():
            raise ScheduleError(f"env 파일이 없음: {env_file}")
        if env_file.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
            # 비밀번호가 들어 있는 파일이다
            raise ScheduleError(f"env 파일을 본인만 읽게 해야 함: chmod 600 {env_file}")
        parts.append(f"set -a && . {shlex.quote(str(env_file.resolve()))} && set +a")
    log = data_dir / "cron.log"
    run = (
        f"{shlex.quote(sys.executable)} -m wetrun run {shlex.quote(str(workflow.resolve()))}"
        f" >> {shlex.quote(str(log))} 2>&1"
    )
    parts.append(run)
    # cron은 %를 줄바꿈으로 바꾸므로 이스케이프한다
    command = " && ".join(parts).replace("%", r"\%")
    return f"{int(m.group(2))} {int(m.group(1))} * * * {command}"
