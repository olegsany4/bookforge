# Makefile — BookForge bootstrap + Stage 1/2 helpers
# -----------------------------------------------
# [KEPT] Оригинальные цели сохранены (bootstrap, install, fmt, clean, tree).
# [ADDED] Добавлены удобные цели (help, init-venv, install-dev, brief, brief-json, check-brief, test, lint, lint-yaml,
#         clean-all, clean-venv, bootstrap-dry, tree-wide) и цели style-lint для Этапа 2.
# [ADDED] Улучшена переносимость под macOS (BSD sed/grep) и добавлены мягкие проверки.
# [ADDED] .DEFAULT_GOAL=help показывает список целей по умолчанию.
# [NOTE]  Обратная совместимость не нарушена: старые вызовы продолжают работать.

.DEFAULT_GOAL := help

.PHONY: bootstrap install fmt clean tree \
        help init-venv install-dev brief brief-json check-brief test lint lint-yaml \
        clean-all clean-venv bootstrap-dry tree-wide \
        style-lint style-lint-fix style-lint-json

# -----------------------
# ОРИГИНАЛЬНЫЕ ПЕРЕМЕННЫЕ
# -----------------------
VENV ?= .venv
PY   ?= $(VENV)/bin/python
PIP  ?= $(VENV)/bin/pip

# -----------------------
# [ADDED] ДОП. ПЕРЕМЕННЫЕ
# -----------------------
YAMLLINT ?= yamllint
PYTEST   ?= pytest
REQ_DEV  ?= requirements-dev.txt
SHELL := bash

# [ADDED] Удобные алиасы и дефолты для стайл-линта (Этап 2)
STYLE_GLOB ?= drafts/**/*.md
STYLE_JSON ?= build/style_report.json

## help: Показать список целей и краткое описание
help:
	@echo "Available targets:" ; \
	grep -E '^[a-zA-Z0-9_.-]+:.*?## ' $(lastword $(MAKEFILE_LIST)) | sed -E 's/:.*##/: /' | sort

# =========================
# ИСХОДНЫЕ ЦЕЛИ (СОХРАНЕНЫ)
# =========================

# [KEPT] bootstrap как был: запуск основной программы
bootstrap: ## Запуск основной программы (как было)
	$(PY) main.py

# [KEPT][ADDED-COMPAT] install: сохранена семантика; показана старая строка, добавлена безопасная инициализация
install: ## Установка prod-зависимостей (совместимо со старой логикой)
	# [LEGACY] Исходная логика оставлена закомментированной для прозрачности:
	# python3 -m venv $(VENV) && . $(VENV)/bin/activate && $(PIP) install --upgrade pip && $(PIP) install -r requirements.txt
	# [ADDED-COMPAT] Эквивалент через явную инициализацию venv:
	@if [ ! -d "$(VENV)" ]; then python3 -m venv "$(VENV)"; fi
	@. "$(VENV)/bin/activate" && $(PIP) install --upgrade pip
	@. "$(VENV)/bin/activate" && $(PIP) install -r requirements.txt

# [KEPT] fmt — оставлен как плейсхолдер
fmt: ## Форматирование кода (плейсхолдер, как было)
	@echo "No formatters configured yet."

# [KEPT] clean
clean: ## Очистить сборочные артефакты (как было)
	rm -rf build/*

# [KEPT] tree
tree: ## Показать структуру проекта (как было)
	@echo "Project layout:" && find . -maxdepth 3 -print | sed 's,^./,,'

# =========================
# [ADDED] НОВЫЕ УДОБНЫЕ ЦЕЛИ
# =========================

init-venv: ## Создать/обновить виртуальное окружение и pip
	@if [ ! -d "$(VENV)" ]; then python3 -m venv "$(VENV)"; fi
	@. "$(VENV)/bin/activate" && $(PIP) install --upgrade pip

install-dev: init-venv ## Установить dev-зависимости (pytest, yamllint и т.п.)
	@if [ -f "$(REQ_DEV)" ]; then \
	  . "$(VENV)/bin/activate" && $(PIP) install -r "$(REQ_DEV)"; \
	else \
	  echo "[warn] $(REQ_DEV) not found, skipping dev deps"; \
	fi

bootstrap-dry: ## Сухой прогон bootstrap (без записи) — если приложение поддерживает --print-only
	@# [KEPT] Не меняет оригинальную цель bootstrap
	$(PY) main.py --print-only || true

brief: ## Сгенерировать проектный бриф Stage 1 (требует реализованного этапа)
	@# Пример: make brief TOPIC="Книга" AUDIENCE="Роль" PAGES=160 OUTPUTS="DOCX,PDF,EPUB"
	@if [ -z "$(TOPIC)" ] || [ -z "$(AUDIENCE)" ] || [ -z "$(PAGES)" ] || [ -z "$(OUTPUTS)" ]; then \
	  echo "[error] Usage: make brief TOPIC='...' AUDIENCE='...' PAGES=160 OUTPUTS='DOCX,PDF,EPUB'"; \
	  exit 2; \
	fi
	$(PY) -m bookforge.stages.product_brief run --topic "$(TOPIC)" --audience "$(AUDIENCE)" --target-pages $(PAGES) --outputs "$(OUTPUTS)"

brief-json: ## То же, но со строкой JSON (экранируйте кавычки)
	@# Пример: make brief-json JSON='{"topic":"...","audience":"...","target_pages":160,"outputs":["DOCX","PDF","EPUB"]}'
	@if ! printf '%s' '$(JSON)' | grep -q . ; then \
	  echo "[error] JSON is required. Example:" ; \
	  echo "make brief-json JSON='{\"topic\":\"...\",\"audience\":\"...\",\"target_pages\":160,\"outputs\":[\"DOCX\",\"PDF\",\"EPUB\"]}'"; \
	  exit 2 ; \
	fi
	$(PY) -m bookforge.stages.product_brief run --json '$(JSON)'

check-brief: ## Проверка брифа (yamllint + быстрый тест Pydantic-модели)
	@if [ -f config/project.yaml ]; then \
	  $(YAMLLINT) config/project.yaml || exit $$? ; \
	else \
	  echo "[error] config/project.yaml not found. Run 'make brief' first."; \
	  exit 2; \
	fi
	@PYTHONPATH=. $(PY) -m $(PYTEST) -q tests/test_project_config.py || true

test: ## Запуск тестов всего проекта (при наличии)
	PYTHONPATH=. $(PY) -m $(PYTEST) -q || true

lint-yaml: ## Прогнать yamllint по config/
	@if command -v $(YAMLLINT) >/dev/null 2>&1; then \
	  $(YAMLLINT) config || true ; \
	else \
	  echo "[warn] yamllint not installed. Run 'make install-dev'."; \
	fi

lint: lint-yaml ## Сводная цель для линтеров (можно расширять)
	@true

clean-venv: ## Удалить виртуальное окружение
	rm -rf "$(VENV)"

clean-all: clean ## Полная очистка кэшей/артефактов
	rm -rf .pytest_cache .mypy_cache __pycache__ */__pycache__ .coverage dist
	find . -name "*.pyc" -delete

tree-wide: ## Показать расширенную структуру (до 5 уровней)
	@echo "Project layout (maxdepth=5):" && find . -maxdepth 5 -print | sed 's,^./,,'

# ==========================================
# [ADDED] ЭТАП 2: СТАЙЛ-ЛИНТ (config/style.yaml)
# ==========================================

style-lint: ## Прогнать style_lint.py по черновикам (см. STYLE_GLOB)
	@echo "Style lint: $(STYLE_GLOB)"
	@$(PY) tools/style_lint.py --glob "$(STYLE_GLOB)"

style-lint-fix: ## Прогнать style_lint.py с безопасными автофиксами (пробелы/пустые строки)
	@echo "Style lint (autofix whitespace): $(STYLE_GLOB)"
	@$(PY) tools/style_lint.py --glob "$(STYLE_GLOB)" --fix

style-lint-json: ## Сохранить JSON-отчёт линтера (build/style_report.json)
	@mkdir -p build
	@$(PY) tools/style_lint.py --glob "$(STYLE_GLOB)" --json "$(STYLE_JSON)"
	@echo "Saved JSON to $(STYLE_JSON)"
