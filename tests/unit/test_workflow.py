import copy

import pytest
import yaml

from wetrun import workflow
from wetrun.workflow import WorkflowError, load

# 계약 3절 예시와 같은 모양. 서비스 이름은 쓰지 않는다
EXAMPLE = {
    "version": 1,
    "repository": {"path": "repo", "password": "env:WETRUN_TEST_PW"},
    "snapshot": {"tag": "svc", "select": "latest"},
    "compose": {
        "files": ["docker-compose.yml"],
        "env_file": ".env",
        "env": {"DATA": "{restore}/data"},
    },
    "refs": "refs.json",
    "steps": [
        {"use": "restore"},
        {"use": "up", "name": "up-database", "services": ["database"]},
        {
            "use": "exec",
            "service": "database",
            "command": ["psql"],
            "stdin": "{restore}/data/backup/db.sql",
        },
        {"use": "up"},
        {"use": "http", "name": "ready", "url": "http://app:80/ping", "timeout": 120},
        {"use": "script", "name": "custom", "image": "x:1", "command": ["/c"], "required": False},
    ],
}


@pytest.fixture
def wf(tmp_path, monkeypatch):
    """예시 워크플로를 고쳐 쓰고 load()하는 함수. 참조 파일은 미리 만들어 둔다."""
    for name in ("docker-compose.yml", ".env", "refs.json"):
        (tmp_path / name).write_text("")
    (tmp_path / "repo").mkdir()
    monkeypatch.setenv("WETRUN_TEST_PW", "secret")
    monkeypatch.setattr(workflow, "builtin_checks", lambda: {"http": ({"url"}, {"expect"})})

    def run(edit=lambda d: None):
        data = copy.deepcopy(EXAMPLE)
        edit(data)
        path = tmp_path / "workflow.yaml"
        path.write_text(yaml.safe_dump(data))
        return load(path)

    return run


def problems(wf, edit) -> str:
    with pytest.raises(WorkflowError) as e:
        wf(edit)
    return "\n".join(e.value.problems)


def test_example_passes_and_fills_defaults(wf):
    steps = wf()["steps"]
    assert steps[0] == {"use": "restore", "name": "restore", "timeout": 300, "required": True}
    assert steps[4]["timeout"] == 120 and steps[5]["required"] is False


def test_restore_placeholder_paths_are_not_checked(wf):
    wf(lambda d: d["steps"][2].update(stdin="{run}/nope.sql"))


def test_rejects_bad_input(wf):
    cases = {
        "모르는 키": lambda d: d["steps"][4].update(bogus=1),
        "모르는 use": lambda d: d["steps"].append({"use": "nope"}),
        "필수 키가 없음": lambda d: d["steps"][4].pop("url"),
        "name이 겹침": lambda d: d["steps"][3].update(name="ready"),
        "환경 변수가 비어 있음": lambda d: d["repository"].update(password="env:WETRUN_UNSET"),
        "파일이 없음": lambda d: d.update(refs="missing.json"),
        "양의 정수": lambda d: d["steps"][4].update(timeout=0),
        "실행기 단계는 false": lambda d: d["steps"][0].update(required=False),
        "지원하지 않는 버전": lambda d: d.update(version=2),
        "steps: 비어 있지 않은": lambda d: d.update(steps=[]),
        "compose.mem_limit": lambda d: d["compose"].update(mem_limit=512),
    }
    for expected, edit in cases.items():
        assert expected in problems(wf, edit), expected


def test_reports_all_problems_at_once(wf):
    def edit(d):
        d["steps"][4].pop("url")
        d["steps"][4]["timeout"] = "fast"

    found = problems(wf, edit)
    assert "필수 키가 없음" in found and "양의 정수" in found


def test_restic_url_repository_is_not_a_local_file(wf):
    wf(lambda d: d["repository"].update(path="sftp:host:/backup"))


def test_builtin_checks_skip_private_and_constantless_modules():
    # 현재 steps/ 모듈에는 상수가 없어 아무것도 검사로 잡히지 않아야 한다
    assert all(not name.startswith("_") for name in workflow.builtin_checks())
