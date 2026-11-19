# 本地常用命令。Windows 若无 make，可直接照 docs/01-运行手册.md 逐条执行。
API_PY := apps/api/.venv/Scripts/python.exe
API_PYTHONPATH := apps/api

.PHONY: help bootstrap db-up db-down api-install api-run api-test worker-once
.PHONY: web-install web-run web-build contract-preview check clean

help:
	@echo "bootstrap db-up db-down api-install api-run api-test worker-once web-install web-run web-build contract-preview check"

bootstrap: api-install web-install
	@echo "依赖安装完成。下一步：make db-up"

db-up:
	docker compose up -d postgres

db-down:
	docker compose down

api-install:
	py -3.13 -m venv apps/api/.venv
	$(API_PY) -m pip install --upgrade pip
	$(API_PY) -m pip install -r apps/api/requirements.lock.txt

api-run:
	$(API_PY) -m uvicorn app.main:app --app-dir apps/api --reload --port 8001

api-test:
	$(API_PY) -m pytest apps/api/tests

worker-once:
	PYTHONPATH=$(API_PYTHONPATH) $(API_PY) -m app.worker.main --once

web-install:
	npm --prefix apps/web ci

web-run:
	npm --prefix apps/web run dev

web-build:
	npm --prefix apps/web run build

contract-preview:
	$(API_PY) contracts/preview.py

check: api-test web-build contract-preview
	@echo "检查通过"

clean:
	@echo "只清理缓存，不动数据库卷"
	$(API_PY) -c "import pathlib,shutil;[shutil.rmtree(p,ignore_errors=True) for p in [pathlib.Path('apps/api/.pytest_cache')]]"
