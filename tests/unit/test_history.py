"""실행 이력 계산 (계약 6절). 가짜 리포트로 확인한다."""

import json

import pytest

from wetrun import report
from wetrun.contract import Status, StepResult
from wetrun.runner import (
    TIMEOUT_CEIL_S,
    TIMEOUT_FLOOR_S,
    adaptive_timeout,
    estimate,
    memory_peaks,
    slow_warnings,
    step_samples,
)


def runs(*durations, name="restore", status="pass", timed_out=False):
    """최근 순 리포트 목록. durations는 오래된 것부터 적는다."""
    return [
        {"steps": [{"name": name, "status": status, "duration_s": d, "timed_out": timed_out}]}
        for d in reversed(durations)
    ]


def restore_step(explicit=False, timeout=300):
    return {"use": "restore", "name": "restore", "timeout": timeout, "_timeout_explicit": explicit}


def test_estimate_matches_rfc6298():
    est, dev = estimate([100.0])
    assert (est, dev) == (100.0, 50.0)  # 첫 표본: Dev = R/2
    est, dev = estimate([100.0, 140.0])
    assert dev == pytest.approx(0.75 * 50 + 0.25 * 40)  # 갱신 전 Est(100)로 계산
    assert est == pytest.approx(0.875 * 100 + 0.125 * 140)


def test_samples_skip_failed_and_timed_out_runs():
    history = runs(10, 11) + runs(99, status="fail") + runs(500, timed_out=True)
    assert sorted(step_samples(history, "restore")) == [10.0, 11.0]


def test_adaptive_timeout_needs_enough_samples():
    assert adaptive_timeout(runs(100, 100, 100, 100), restore_step()) is None  # 4개
    t = adaptive_timeout(runs(100, 100, 100, 100, 100), restore_step())
    assert TIMEOUT_FLOOR_S <= t < 300  # 안정적이면 기본값보다 짧아진다


def test_adaptive_timeout_respects_yaml_and_step_kind():
    history = runs(*[100] * 6)
    assert adaptive_timeout(history, restore_step(explicit=True)) is None
    check = {"use": "http", "name": "restore", "timeout": 120}
    assert adaptive_timeout(history, check) is None  # 검사의 시간 제한은 판정 기준


def test_adaptive_timeout_backs_off_after_timeout_and_is_bounded():
    # 표본이 없어도 직전에 끊겼으면 2배 (상한 안에서)
    assert adaptive_timeout(runs(300, timed_out=True), restore_step()) == TIMEOUT_CEIL_S
    assert adaptive_timeout(runs(*[1] * 6), restore_step()) == TIMEOUT_FLOOR_S


def test_slow_warning_only_with_history_and_never_changes_status():
    history = runs(*[100] * 6)
    slow = StepResult("restore", "restore", Status.PASS, duration_s=400)
    normal = StepResult("restore", "restore", Status.PASS, duration_s=105)
    assert "평소보다 느림" in slow_warnings(history, [slow])[0]
    assert slow_warnings(history, [normal]) == []
    assert slow_warnings(runs(100), [slow]) == []  # 표본 부족


def test_memory_peaks_takes_max_per_service():
    history = [{"memory_peak_bytes": {"db": 100, "app": 5}}, {"memory_peak_bytes": {"db": 300}}]
    assert memory_peaks(history) == {"db": 300, "app": 5}


def test_load_history_filters_sorts_and_skips_broken(tmp_path):
    def write(name, **data):
        (tmp_path / f"{name}.json").write_text(json.dumps(data))

    write("a", workflow_id="w1", started_at="2026-11-14T10:00:00+09:00")
    write("b", workflow_id="w1", started_at="2026-11-14T12:00:00+09:00")
    write("c", workflow_id="other", started_at="2026-11-14T13:00:00+09:00")
    (tmp_path / "broken.json").write_text("{not json")
    found = report.load_history(tmp_path, "w1")
    assert [d["started_at"][11:13] for d in found] == ["12", "10"]  # 최근 순
    assert report.load_history(tmp_path, "w1", limit=1)[0]["started_at"].startswith("2026-11-14T12")
    assert report.load_history(tmp_path / "없는폴더", "w1") == []
    assert report.load_history(tmp_path, "") == []
