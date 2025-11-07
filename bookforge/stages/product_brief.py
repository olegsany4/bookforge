from __future__ import annotations

import argparse
import json
import re
import sys
from io import StringIO
from pathlib import Path
from typing import Any, Dict, List

import yaml
from pydantic import ValidationError

from bookforge.models.project import ProjectConfig


PROMPT_PATH = Path("prompts/producer.system.md")
OUTPUT_PATH = Path("config/project.yaml")


# =========================
# YAML dumper (yamllint-ok)
# =========================

class AlwaysFoldDumper(yaml.SafeDumper):
    """
    - Запрещаем indentless-режим (исправляет '-  value').
    - Всегда представляем строки как folded block scalars ('>') с переносами.
    """
    def increase_indent(self, flow: bool = False, indentless: bool = False):
        return super().increase_indent(flow, indentless=False)

def _wrap_text(s: str, width: int = 72) -> str:
    """
    Жёстко переносим длинные строки по пробелам до ширины width.
    Если уже есть переносы — уважаем их.
    """
    s = s.replace("\t", " ")
    if "\n" in s or len(s) <= width:
        return s
    words = s.split(" ")
    lines: List[str] = []
    cur: List[str] = []
    cur_len = 0
    for w in words:
        if not w:
            continue
        if len(w) > width:
            if cur:
                lines.append(" ".join(cur))
                cur, cur_len = [], 0
            for i in range(0, len(w), width):
                lines.append(w[i:i+width])
            continue
        add = len(w) if not cur else len(w) + 1
        if cur_len + add <= width:
            cur.append(w)
            cur_len += add
        else:
            lines.append(" ".join(cur))
            cur = [w]
            cur_len = len(w)
    if cur:
        lines.append(" ".join(cur))
    return "\n".join(lines)

def _prepare_strings_folded(obj: Any, width: int = 72) -> Any:
    """
    Рекурсивно оборачиваем ВСЕ строки в folded-блоки, добавляя переносы.
    """
    if isinstance(obj, dict):
        return {k: _prepare_strings_folded(v, width) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_prepare_strings_folded(v, width) for v in obj]
    if isinstance(obj, str):
        return _wrap_text(obj, width)
    return obj

def _represent_str_as_folded(dumper: yaml.Dumper, data: str):
    # Представляем любую строку блочным скалярным типом '>' (folded)
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=">")

AlwaysFoldDumper.add_representer(str, _represent_str_as_folded)

_HYPHEN_FIX_RE = re.compile(r"^(\s*)- {2,}(?=\S)", re.MULTILINE)

def dump_yaml_pretty_str(data: Dict[str, Any]) -> str:
    """
    Возвращает YAML строку, дружелюбную к yamllint:
      - explicit_start: '---'
      - indent=4
      - width=78 (сам YAML), строки уже порезаны до 72
      - default_flow_style=False
      - убираем возможные двойные пробелы после '-'
    """
    prepared = _prepare_strings_folded(data, width=72)
    buf = StringIO()
    yaml.dump(
        prepared,
        buf,
        Dumper=AlwaysFoldDumper,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        explicit_start=True,
        width=78,
        indent=4,
    )
    s = buf.getvalue()
    s = _HYPHEN_FIX_RE.sub(r"\1- ", s)
    return s

def dump_yaml_pretty_file(data: Dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = dump_yaml_pretty_str(data)
    path.write_text(text, encoding="utf-8")


# ==================================
# Deterministic content (Stage 1)
# ==================================

def _deterministic_yaml_from_input(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Фолбэк-генератор YAML без LLM: собирает корректный скелет под валидацию."""
    topic: str = payload["topic"]
    audience: str = payload["audience"]
    target_pages: int = int(payload["target_pages"])
    outputs: List[str] = payload.get("outputs", ["DOCX", "PDF", "EPUB"])

    # Простая эвристика распределения страниц (в сумме == target_pages)
    p1 = max(20, round(target_pages * 0.18))
    p2 = max(40, round(target_pages * 0.38))
    p3 = max(30, round(target_pages * 0.32))
    p4 = target_pages - (p1 + p2 + p3)
    if p4 < 10:
        # минимально 10 страниц на Часть IV — докинем с Части II
        delta = 10 - p4
        p2 = max(40, p2 - delta)
        p4 = 10

    data = {
        "topic": topic,
        "positioning": {
            "for_whom": audience,
            "problem_jobs": [
                "Быстрое, воспроизводимое создание книги с контролем качества"
            ],
            "unique_angle": "Инженерный пайплайн с KPI и автоматическими проверками качества",
        },
        "audience": {
            "primary": audience,
            "secondary": "",
            "prerequisites": ["Базовые знания Git", "Опыт чтения YAML/JSON"],
        },
        "scope": {
            "target_pages": target_pages,
            "page_budget": [
                {"part": "I. Концепт и бриф", "pages": p1},
                {"part": "II. Архитектура", "pages": p2},
                {"part": "III. Качество и продакшн", "pages": p3},
                {"part": "IV. Кейсы и чек-листы", "pages": p4},
            ],
            "in_scope": ["Дизайн ролей агентов и их промптов"],
            "out_of_scope": ["Обучение собственных LLM с нуля"],
        },
        "reader_questions": [
            "Как быстро получить рабочий пайплайн книги под ключ?",
            "Какие роли агентов обязательны и как они взаимодействуют?",
            "Как измерять качество и ловить деградации?",
        ],
        "objectives": [
            "Зафиксировать архитектуру и роли (≤10 страниц) к концу Части I",
            "Собрать MVP пайплайна с автопроверками к концу Части II",
            "Покрытие упражнений ≥20% страниц к завершению Части III",
            "Экспорт DOCX/PDF/EPUB без ошибок к финалу проекта",
        ],
        "structure_outline": [
            {
                "part": "I. Концепт и бриф",
                "chapters": ["Позиционирование", "Карта ролей", "Контракты I/O"],
            },
            {
                "part": "II. Архитектура агентов",
                "chapters": ["Оркестрация", "Хранилище и версии", "Промпт-инжиниринг"],
            },
            {
                "part": "III. Качество и продакшн",
                "chapters": ["KPI и метрики", "Проверки и тесты", "CI/CD публикации"],
            },
            {
                "part": "IV. Кейсы и чек-листы",
                "chapters": ["Внедрение A", "Внедрение B", "Антипаттерны"],
            },
        ],
        "outputs": outputs,
        "acceptance_criteria": {
            "readability": {
                "max_sentence_avg": 17,
                "passive_voice_max": 8,
                "simple_words_min": 75,
            },
            "structure": {
                "chapter_len_variance_max": 20,
                "each_chapter_has": ["hook", "objective", "example", "checkpoint"],
            },
            "factuality": {
                "claim_evidence_coverage_min": 80,
                "zero_critical_errors_sample": 30,
            },
            "applicability": {"exercises_share_min": 20, "case_studies_min": 6},
            "production": {
                "styles_validated": True,
                "export_success": ["DOCX", "PDF", "EPUB"],
            },
        },
        "risks_assumptions": {
            "risks": ["Зависимость от нестабильных LLM-API"],
            "mitigations": ["Кэширование, версионирование промптов и шаблонов"],
            "assumptions": ["Доступна инфраструктура CI/CD"],
        },
        "workflow_notes": {
            "sources_policy": "Каждый факт имеет ссылку на проверяемый источник",
            "glossary_policy": "Термины вводятся при первом употреблении и сводятся в глоссарий",
        },
    }
    return data


# =========================
# KPI table (stdout)
# =========================

def _print_kpi_table() -> None:
    table = [
        "| Метрика | Цель/порог | Как меряем | Чек-пойнт |",
        "|---|---|---|---|",
        "| Читаемость | средняя длина ≤ 17 слов; пассив ≤ 8%; простые ≥ 75% | статический анализ текста | по завершении каждой части |",
        "| Структура | разброс длины глав ≤ 20%; hook/objective/example/checkpoint в каждой | скрипт проверки оглавления + чек-лист | при слиянии в main |",
        "| Фактичность | ≥ 80% утверждений со ссылками; 0 критических ошибок в n=30 | ручная выборка + линтер ссылок | перед релиз-кандидатом |",
        "| Прикладность | ≥ 20% страниц с упражнениями; ≥ 6 кейсов | счётчик макета | конец Части III |",
        "| Продакшн | Успешный экспорт DOCX/PDF/EPUB | CI-джоб экспортов | релиз |",
    ]
    print("\n".join(table))


# =========================
# CLI
# =========================

def run(args: argparse.Namespace) -> int:
    # вход может прийти как FLAGS или как JSON-строка
    if args.json:
        try:
            payload = json.loads(args.json)
        except json.JSONDecodeError as e:
            print(f"[error] invalid JSON: {e}", file=sys.stderr)
            return 2
    else:
        if not all([args.topic, args.audience, args.target_pages, args.outputs]):
            print(
                "[error] provide either --json or all of --topic/--audience/--target-pages/--outputs",
                file=sys.stderr,
            )
            return 2
        payload = {
            "topic": args.topic,
            "audience": args.audience,
            "target_pages": int(args.target_pages),
            "outputs": [x.strip() for x in args.outputs.split(",")],
        }

    data = _deterministic_yaml_from_input(payload)

    # Валидация pydantic-моделью
    try:
        ProjectConfig.model_validate(data)
    except ValidationError as e:
        print("[error] project.yaml validation failed:\n", e, file=sys.stderr)
        return 3

    # Дамп YAML в файл «по стандарту»
    dump_yaml_pretty_file(data, OUTPUT_PATH)

    # Вывод KPI-таблицы в stdout (по ТЗ)
    _print_kpi_table()
    print(f"\n[ok] wrote {OUTPUT_PATH.as_posix()}")
    return 0


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bookforge-product-brief", description="Stage 1: Product Brief generator"
    )
    sub = parser.add_subparsers(dest="cmd")

    p = sub.add_parser("run", help="Generate config/project.yaml from JSON or flags")
    p.add_argument(
        "--json",
        type=str,
        help='Raw JSON: {"topic":"...","audience":"...","target_pages":160,"outputs":["DOCX","PDF","EPUB"]}',
    )
    p.add_argument("--topic", type=str)
    p.add_argument("--audience", type=str)
    p.add_argument("--target-pages", type=int)
    p.add_argument("--outputs", type=str, help="Comma-separated: DOCX,PDF,EPUB")
    p.set_defaults(func=lambda a: run(a))

    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
