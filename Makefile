# Wetrun 개발용 명령. Windows는 WSL2 안에서 실행.
# testenv 관련 타깃(env-up, seed, backup 등)은 testenv 담당이 추가.

install:
	uv sync

fmt:
	uv run ruff format .
	uv run ruff check --fix .

lint:
	uv run ruff format --check .
	uv run ruff check .

test:
	uv run pytest

# testenv: 개발·평가용 Immich (testenv/README.md)
env-up:
	testenv/up.sh

env-down:
	testenv/down.sh

env-clean:
	testenv/down.sh --clean

.PHONY: install fmt lint test env-up env-down env-clean
