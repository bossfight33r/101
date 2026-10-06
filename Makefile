PY := .venv/bin/python
UV ?= uv

.PHONY: setup setup-mac test lint fmt sandbox-image doctor bot selftest

setup:
	$(UV) venv --python 3.12 .venv
	$(UV) pip install --python $(PY) -e ".[dev]"

setup-mac:
	command -v ffmpeg >/dev/null || brew install ffmpeg
	$(UV) venv --python 3.12 .venv
	$(UV) pip install --python $(PY) -e ".[dev,asr,mac]"

sandbox-image:
	docker build -t techstudio-sandbox:latest docker/studio

test:
	$(PY) -m pytest

lint:
	.venv/bin/ruff check src tests
	.venv/bin/ruff format --check src tests

fmt:
	.venv/bin/ruff format src tests
	.venv/bin/ruff check --fix src tests

doctor:
	.venv/bin/studio doctor

bot:
	.venv/bin/studio bot

selftest:
	.venv/bin/studio doctor --strict
	.venv/bin/studio selftest
