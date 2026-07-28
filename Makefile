.PHONY: install dev test lint format format-check typecheck shellcheck frontend frontend-check build linux-installer check clean

install:
	python3 -m pip install .

dev:
	python3 -m pip install -e '.[dev]'

test:
	pytest

lint:
	ruff check .

format:
	ruff format .

format-check:
	ruff format --check .

typecheck:
	mypy src/mia

shellcheck:
	bash -n install.sh uninstall.sh install-mia.sh scripts/build_linux_installer.sh
	@if command -v shellcheck >/dev/null 2>&1; then shellcheck -x install.sh uninstall.sh install-mia.sh scripts/build_linux_installer.sh; else echo 'shellcheck not installed'; fi

frontend:
	npm --prefix frontend-workbench run build
	npm --prefix frontend-discover run build

frontend-check:
	npm --prefix frontend-workbench run lint
	npm --prefix frontend-discover run lint


linux-installer:
	bash scripts/build_linux_installer.sh

build: frontend
	python3 -m build
	python3 -m twine check dist/*

check: lint test shellcheck frontend-check build

clean:
	rm -rf build dist .pytest_cache .ruff_cache .mypy_cache *.egg-info src/*.egg-info frontend-workbench/node_modules frontend-discover/node_modules
