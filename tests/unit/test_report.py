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
