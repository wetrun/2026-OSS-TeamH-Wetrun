"""`wetrun run` 진행 표시. 터미널(stderr)일 때만 쓴다.

실행 중인 단계를 회색 한 줄로 두고 마침표(. .. ...)와 경과 시간을 갱신하다가, 끝나면 같은 줄을
판정(색)·걸린 시간·메시지로 덮어쓴다. 끝난 줄이 단계 표가 되므로 요약에서는 단계 표를 뺀다.
터미널이 아니면(cron 로그, 파일) 아무것도 쓰지 않고, 요약이 예전처럼 단계 표를 싣는다.
NO_COLOR가 있으면 색을 끈다. 메시지는 실행기가 비밀 값을 가린 뒤 넘긴다.
"""

import os
import sys
import threading
import time

DOING = {"restore": "스냅샷 복원", "up": "서비스 기동", "exec": "명령 실행"}  # 나머지는 검사
COLORS = {"pass": "32", "fail": "31", "error": "33"}  # 초록·빨강·노랑. skipped는 회색
DIM = "2"
NAME_WIDTH = 12


class Progress:
    def __init__(self, out=None, interval: float = 0.4) -> None:
        self.out = out or sys.stderr
        self.live = hasattr(self.out, "isatty") and self.out.isatty()
        self.color = self.live and not os.environ.get("NO_COLOR")
        self.interval = interval
        self._lock = threading.Lock()
        self._stop: threading.Event | None = None
        self._thread: threading.Thread | None = None

    def start(self, index: int, total: int, name: str, use: str) -> None:
        """단계 시작. 터미널이면 끝날 때까지 회색 줄을 갱신한다."""
        self._begin(f"[{index}/{total}] {name:<{NAME_WIDTH}} {DOING.get(use, '검사')} 중")

    def done(
        self, index: int, total: int, name: str, status: str, seconds: float, message: str = ""
    ) -> None:
        verdict = self._paint(f"{status:<7}", COLORS.get(status, DIM))
        line = f"[{index}/{total}] {name:<{NAME_WIDTH}} {verdict} {seconds:5.1f}초  {message}"
        self._end(line.rstrip())

    def cleanup_start(self) -> None:
        self._begin("정리 중")

    def cleanup_done(self, ok: bool, seconds: float) -> None:
        word = self._paint("완료", COLORS["pass"]) if ok else self._paint("실패", COLORS["fail"])
        self._end(f"정리 {word} {seconds:.1f}초")

    # ---- 내부 ----

    def _begin(self, label: str) -> None:
        self._halt()
        if not self.live:
            return
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._spin, args=(label, self._stop), daemon=True)
        self._thread.start()

    def _spin(self, label: str, stop: threading.Event) -> None:
        t0, tick = time.monotonic(), 0
        while True:
            dots = "." * (tick % 3 + 1)
            elapsed = int(time.monotonic() - t0)
            self._write("\r\033[2K" + self._paint(f"{label}{dots:<3} {elapsed}초", DIM))
            tick += 1
            if stop.wait(self.interval):
                return

    def _end(self, line: str) -> None:
        self._halt()
        if self.live:
            self._write("\r\033[2K" + line + "\n")

    def _halt(self) -> None:
        if self._stop:
            self._stop.set()
            self._thread.join()
            self._stop = self._thread = None

    def _paint(self, text: str, code: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.color else text

    def _write(self, text: str) -> None:
        with self._lock:
            self.out.write(text)
            self.out.flush()
