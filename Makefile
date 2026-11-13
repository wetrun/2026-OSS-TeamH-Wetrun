# Wetrun 개발용 명령. Windows는 WSL2 안에서 실행.

install:
	uv sync

fmt:
	uv run ruff format .
	uv run ruff check --fix .

# CI도 이 명령을 그대로 쓴다
lint:
	uv run ruff format --check .
	uv run ruff check .
	@if grep -rIil immich wetrun/; then echo "wetrun/에 서비스 이름이 있음. profiles/<서비스>/로 옮긴다"; exit 1; fi

test:
	uv run pytest

# testenv: 개발·평가용 Immich (testenv/README.md)
env-up:
	testenv/up.sh

seed:
	uv run python testenv/seed.py

backup:
	testenv/backup.sh

# 새로 clone한 뒤 이 한 줄로 Immich + 테스트 데이터 + 백업을 만든다
env: env-up seed backup

env-down:
	testenv/down.sh

env-clean:
	testenv/down.sh --clean

.PHONY: install fmt lint test env env-up seed backup env-down env-clean
