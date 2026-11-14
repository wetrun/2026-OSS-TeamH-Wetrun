import json
import stat

from wetrun import report
from wetrun.contract import RunResult, Status, StepResult


def result(*steps, cleanup_errors=()):
    return RunResult(
        run_id="r1",
        snapshot_id="abcdef1234567890",
        workflow_sha256="0" * 64,
        started_at="2026-11-14T09:00:00+09:00",
        duration_s=70.5,
        steps=list(steps),
        cleanup_errors=list(cleanup_errors),
    )


PASSED = [
    StepResult("restore", "restore", Status.PASS, duration_s=2.0),
    StepResult("photos", "ref_files", Status.PASS, message="파일 5개 전부 확인", duration_s=1.2),
]


def test_json_has_verdict_and_exit_code():
    data = report.to_dict(result(*PASSED))
    assert data["verdict"] == "pass"
    assert data["exit_code"] == 0
    assert data["steps"][1]["status"] == "pass"
    json.dumps(data)  # 그대로 JSON으로 쓸 수 있어야 함


def test_fail_verdict_and_skipped_steps():
    data = report.to_dict(
        result(
            StepResult("photos", "ref_files", Status.FAIL, message="체크섬이 다른 파일 1개"),
            StepResult("custom", "script", Status.SKIPPED),
        )
    )
    assert (data["verdict"], data["exit_code"]) == ("fail", 1)


def test_cleanup_error_wins_exit_code():
    data = report.to_dict(result(*PASSED, cleanup_errors=["network 남음"]))
    assert data["verdict"] == "pass"
    assert data["exit_code"] == 3


def test_summary_shows_messages_not_evidence():
    step = StepResult(
        "restore-db",
        "exec",
        Status.FAIL,
        message="명령이 실패함",
        evidence={"stderr": ["ERROR: x"]},
    )
    text = report.summary(result(step))
    assert "FAIL" in text and "명령이 실패함" in text
    assert "ERROR: x" not in text  # stderr는 JSON 리포트에만


def test_summary_marks_optional_and_cleanup():
    step = StepResult("custom", "script", Status.FAIL, required=False, message="x")
    text = report.summary(result(*PASSED, step, cleanup_errors=["volume 남음"]))
    assert "(선택)" in text
    assert "정리 오류 1개" in text


def test_next_action_points_to_first_bad_required_step():
    steps = [
        StepResult("restore", "restore", Status.PASS),
        StepResult("custom", "script", Status.FAIL, required=False),  # 선택 단계는 판정 밖
        StepResult("restore-db", "exec", Status.FAIL, message="명령이 실패함"),
        StepResult("up", "up", Status.SKIPPED),
    ]
    text = report.summary(result(*steps))
    assert "할 일: 백업이나 복구한 데이터에 문제가 있음. restore-db 단계를 확인" in text
    assert "custom 단계" not in text


def test_next_action_for_error_says_not_a_backup_problem():
    steps = [
        StepResult("ready", "http", Status.ERROR),
        StepResult("photos", "ref_files", Status.FAIL),
    ]
    actions = report.next_actions(report.to_dict(result(*steps)))
    assert len(actions) == 1
    assert "백업이 망가졌다는 뜻은 아님" in actions[0] and "ready 단계" in actions[0]


def test_next_action_for_cleanup_and_nothing_for_pass():
    assert report.next_actions(report.to_dict(result(*PASSED))) == []
    assert "할 일" not in report.summary(result(*PASSED))
    actions = report.next_actions(report.to_dict(result(*PASSED, cleanup_errors=["network 남음"])))
    assert actions == ["남은 자원을 직접 지워야 함 (아래 정리 오류)"]


def test_long_message_is_cut():
    step = StepResult("ready", "http", Status.FAIL, message="가" * 1000)
    line = [ln for ln in report.summary(result(step)).splitlines() if "ready" in ln][0]
    assert len(line) < 300


def test_secrets_masked_everywhere():
    step = StepResult(
        "x",
        "exec",
        Status.ERROR,
        message="pw=hunter2",
        evidence={"e": "hunter2", "stderr": ["line hunter2"], "hunter2": 1},
    )
    data = report.to_dict(result(step, cleanup_errors=["hunter2 남음"]), secrets=["hunter2"])
    assert "hunter2" not in json.dumps(data, ensure_ascii=False)
    assert data["steps"][0]["message"] == "pw=***"


def test_secret_same_as_status_word_keeps_verdict():
    data = report.to_dict(result(*PASSED), secrets=["pass"])
    assert data["verdict"] == "pass"
    assert [s["status"] for s in data["steps"]] == ["pass", "pass"]


def test_numeric_secret_keeps_numbers():
    step = StepResult("restore", "restore", Status.PASS, evidence={"bytes": 54305072})
    data = report.to_dict(result(step), secrets=["5430"])
    assert data["steps"][0]["evidence"]["bytes"] == 54305072
    assert data["exit_code"] == 0


def test_save_writes_private_json(tmp_path):
    path = report.save(result(*PASSED), tmp_path / "runs")
    assert path.name == "r1.json"
    assert json.loads(path.read_text())["verdict"] == "pass"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


# ---- 경고·백업 나이 (contract 6절) ----


def test_warning_shows_as_note_under_todo():
    step = StepResult("photos", "ref_files", Status.FAIL, message="빠진 파일 1개")
    r = result(step)
    r.warnings = ["검사한 백업이 6일 전 것", "restore-db가 평소보다 느림"]
    lines = report.summary(r).splitlines()
    assert lines[1].startswith("할 일: ")
    assert lines[2:4] == ["참고: 검사한 백업이 6일 전 것", "참고: restore-db가 평소보다 느림"]
    assert report.to_dict(r)["verdict"] == "fail"  # 경고는 판정을 바꾸지 않음


def test_warnings_are_masked():
    r = result(*PASSED)
    r.warnings = ["느림 (pw=hunter2)"]
    assert report.to_dict(r, secrets=["hunter2"])["warnings"] == ["느림 (pw=***)"]


def test_summary_shows_backup_age():
    r = result(*PASSED)
    r.snapshot_time = "2026-11-08T07:10:16.123456789+09:00"  # restic은 나노초까지 적는다
    assert "스냅샷 abcdef12 (6일 전) · 70.5초" in report.summary(r)


def test_backup_age():
    run = "2026-11-14T09:00:00+09:00"

    def age(snap, ran=run):
        return report.backup_age({"snapshot_time": snap, "started_at": ran})

    assert age("2026-11-14T08:30:00+09:00") == "1시간 안"
    assert age("2026-11-13T14:00:00Z") == "10시간 전"  # 시간대가 달라도 같은 순간끼리 비교
    assert age("2026-11-11T08:59:59+09:00") == "3일 전"
    for unknown in ["", "어제", "2026-11-14T08:00:00", "2026-11-15T09:00:00+09:00"]:
        assert age(unknown) == ""  # 형식 오류, 시간대 없음, 미래(시계 어긋남)
    assert report.backup_age({}) == ""  # 옛 리포트


def test_backup_age_rounds_like_runner_warning():
    # 같은 카드에 실행기 경고(#40)의 "6일 전"과 꼬리의 "5일 전"이 같이 보이지 않게
    from datetime import datetime

    from wetrun.runner import stale_snapshot_warning

    snap, ran = "2026-11-08T19:00:00.123456789+09:00", "2026-11-14T09:00:00+09:00"  # 5.58일
    (warning,) = stale_snapshot_warning(snap, now=datetime.fromisoformat(ran))
    assert warning.startswith("검사한 백업이 6일 전 것")
    assert report.backup_age({"snapshot_time": snap, "started_at": ran}) == "6일 전"
