from wetrun.contract import EXIT_CLEANUP, RunResult, Status, StepResult, exit_code, verdict

P, F, E, S = Status.PASS, Status.FAIL, Status.ERROR, Status.SKIPPED


def steps(*statuses: Status, required: bool = True) -> list[StepResult]:
    return [StepResult(f"s{i}", "http", st, required) for i, st in enumerate(statuses)]


def test_all_required_pass():
    assert verdict(steps(P, P)) == P


def test_required_fail_then_skipped_is_fail():
    assert verdict(steps(P, F, S)) == F


def test_required_error_is_error():
    assert verdict(steps(E, S)) == E


def test_skipped_required_without_failure_is_not_pass():
    assert verdict(steps(P, S)) == E


def test_no_required_steps_is_not_pass():
    assert verdict(steps(P, required=False)) == E


def test_optional_fail_does_not_change_verdict():
    assert verdict(steps(P) + steps(F, required=False)) == P


def test_cleanup_failure_overrides_exit_code():
    r = RunResult("r", "snap", "sha", "t", 1.0, steps(P), cleanup_errors=["x"])
    assert exit_code(r) == EXIT_CLEANUP
