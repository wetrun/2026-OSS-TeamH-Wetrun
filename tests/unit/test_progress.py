import io
import re
import time

from wetrun.progress import Progress


class Tty(io.StringIO):
    def isatty(self):
        return True


def test_not_a_terminal_writes_nothing():
    """cron 로그·파일에는 요약의 단계 표만 남는다 (같은 내용을 두 번 쓰지 않는다)."""
    out = io.StringIO()
    p = Progress(out)
    assert not p.live
    p.start(1, 2, "restore", "restore")
    p.done(1, 2, "restore", "pass", 3.4, "스냅샷 복원")
    p.cleanup_start()
    p.cleanup_done(True, 0.5)
    assert out.getvalue() == ""


def test_terminal_shows_gray_dots_and_time_then_colored_verdict(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    out = Tty()
    p = Progress(out, interval=0.01)
    p.start(3, 6, "restore-db", "exec")
    time.sleep(0.08)
    p.done(3, 6, "restore-db", "fail", 31.4, "psql 종료 코드 3")
    text = out.getvalue()
    assert "\033[2m[3/6] restore-db   명령 실행 중.   0초" in text  # 실행 중: 회색
    assert "중.. " in text and "중..." in text  # 마침표가 늘었다 줄었다 한다
    last = text.rsplit("\r\033[2K", 1)[1]  # 마지막에 같은 줄을 지우고 덮어쓴다
    assert (
        last == "[3/6] restore-db   \033[31mfail   \033[0m  31.4초  psql 종료 코드 3\n"
    )  # 판정만 빨강
    time.sleep(0.03)
    assert out.getvalue() == text  # 끝난 뒤에는 더 쓰지 않는다


def test_no_color_keeps_line_updates_without_colors(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    out = Tty()
    p = Progress(out, interval=0.01)
    p.start(1, 1, "photos", "ref_files")
    time.sleep(0.02)
    p.done(1, 1, "photos", "pass", 2.0)
    text = out.getvalue()
    assert "검사 중" in text and "\r\033[2K" in text
    assert not re.search(r"\033\[\d+m", text)
