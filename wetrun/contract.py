"""실행기와 검사가 주고받는 결과 형식과 판정 규칙. 자세한 계약은 docs/contract.md."""

from dataclasses import dataclass, field
from enum import StrEnum


class Status(StrEnum):
    PASS = "pass"  # 통과
    FAIL = "fail"  # 복구 검증 실패 (백업·복구 문제)
    ERROR = "error"  # 실행 조건 오류 (입력·도구·시간 초과 문제)
    SKIPPED = "skipped"  # 앞 필수 단계가 통과하지 못해 실행하지 않음


@dataclass
class StepResult:
    name: str
    use: str
    status: Status
    required: bool = True
    message: str = ""
    evidence: dict = field(default_factory=dict)  # 비밀 값 없음
    duration_s: float = 0.0


@dataclass
class RunResult:
    run_id: str
    snapshot_id: str
    workflow_sha256: str
    started_at: str  # ISO 8601
    duration_s: float
    steps: list[StepResult]
    images: dict[str, str] = field(default_factory=dict)  # 서비스 → 이미지 digest
    cleanup_errors: list[str] = field(default_factory=list)


# 검사 컨테이너 종료 코드 → 단계 상태. 그 외 코드·result.json 없음·시간 초과는 ERROR
CHECK_EXIT_STATUS = {0: Status.PASS, 1: Status.FAIL}

# CLI 종료 코드
EXIT_PASS, EXIT_FAIL, EXIT_ERROR, EXIT_CLEANUP = 0, 1, 2, 3


def verdict(steps: list[StepResult]) -> Status:
    """전체 판정. 필수 단계가 모두 pass일 때만 pass. 미실행 필수 단계는 통과로 보지 않는다."""
    required = [s.status for s in steps if s.required]
    if not required or Status.ERROR in required:
        return Status.ERROR
    if Status.FAIL in required:
        return Status.FAIL
    if all(s == Status.PASS for s in required):
        return Status.PASS
    return Status.ERROR  # 실패 없이 건너뛴 필수 단계: 실행기 버그


def exit_code(result: RunResult) -> int:
    """정리 실패는 운영자가 직접 치워야 하므로 판정보다 우선한다."""
    if result.cleanup_errors:
        return EXIT_CLEANUP
    return {Status.PASS: EXIT_PASS, Status.FAIL: EXIT_FAIL}.get(verdict(result.steps), EXIT_ERROR)
