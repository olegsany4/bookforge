#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# file: tools/style_lint.py
"""
Style linter for BookForge Stage 2.

Checks .md/.txt files against config/style.yaml:
- Sentence length (target 8–16, max 22 words)
- Paragraph length (2–5 sentences)
- Passive voice heuristics (RU)
- Banned phrases
- Vague claims without nearby metrics
- Terminology hints

CLI:
  python tools/style_lint.py [FILES|DIRS ...]
  Options:
    --json PATH             Save JSON report
    --fix                   Apply safe autofixes (whitespace/blank lines only)
    --glob PATTERN          Glob to expand inside dirs (default: **/*.md and **/*.txt)
    --exclude PATTERN       Exclude glob (can repeat). Defaults: .venv, .pytest_cache, build, dist, .git,
                            node_modules, __pycache__, site-packages, *.dist-info
    --max-sent N            Override max sentence length
    --target-len A,B        Override target sentence length range
    --max-para N            Override max sentences per paragraph
    --passive-allow         Allow passive voice
    --require-metrics 0|1   Toggle vague-claim metric requirement

Exit codes: 0 ok, 1 errors, 2 usage/no files.
"""
from __future__ import annotations
import argparse
import fnmatch
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

try:
    import yaml
except ImportError:
    print("[ERR] PyYAML not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(2)

ROOT = Path(__file__).resolve().parents[1]
CFG  = ROOT / "config/style.yaml"

# --- RU sentence splitting with common abbrev guards ---
# NOTE: avoid variable-width lookbehind. Split first, then merge on abbreviations.
ABBREV_LIST = [
    "т.е.", "т.к.", "и т.д.", "и т.п.", "д.р.",
    "г.", "стр.", "рис.",
]
SENT_SPLIT_SIMPLE_RE = re.compile(r"(?<=[.!?])\s+")
WORD_RE = re.compile(r"[А-Яа-яA-Za-z0-9ёЁ\-]+")

PASSIVE_HINTS = [
    r"\bбыло\s+принято\s+решение\b",
    r"\bбыл[аио]?\s+\w+н[а-я]+\b",      # был утвержден/а/о/ы
    r"\bпроизведен[аоы]?\b",
]
PASSIVE_RE = re.compile("|".join(PASSIVE_HINTS), re.IGNORECASE)

VAGUE_CLAIMS = [
    r"\bзначительно\b",
    r"\bсущественно\b",
    r"\bбыстро\b",
    r"\bэффективно\b",
    r"\bна порядок\b",
]
VAGUE_RE = re.compile("|".join(VAGUE_CLAIMS), re.IGNORECASE)
METRIC_RE = re.compile(r"\d+\s?(%|мин|час|дн|шаг|правил|MB|GB|стр|сек)\b", re.IGNORECASE)

TERMINOLOGY_KEYS = [
    "агент", "оркестратор", "планировщик", "критик", "редактор", "рутер",
    "память", "контекстное_окно", "RAG", "инструмент", "политика",
    "JSON_схема", "пайплайн", "idempotency", "телеметрия", "артефакт",
    "чеклист", "дедупликация", "грейдинг"
]

# Default exclude globs to avoid vendor/venv noise
DEFAULT_EXCLUDES = [
    ".venv/**", ".pytest_cache/**", "build/**", "dist/**", ".git/**",
    "node_modules/**", "**/__pycache__/**", "**/site-packages/**", "**/*.dist-info/**",
]

def load_cfg() -> Dict[str, Any]:
    if not CFG.exists():
        print(f"[ERR] Missing {CFG}", file=sys.stderr)
        sys.exit(2)
    with open(CFG, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return cfg or {}

def split_paragraphs(text: str) -> List[str]:
    parts = re.split(r"\n\s*\n", text.strip())
    return [p.strip() for p in parts if p.strip()]

def _ends_with_abbrev(chunk: str) -> bool:
    s = chunk.strip()
    # Normalize spacing for multi-token abbreviations (e.g., "и т.д.")
    s_norm = re.sub(r"\s+", " ", s)
    s_norm_lower = s_norm.lower()
    return any(s_norm_lower.endswith(abbr) for abbr in ABBREV_LIST)

def split_sentences(para: str) -> List[str]:
    # First naive split by punctuation + whitespace
    raw = SENT_SPLIT_SIMPLE_RE.split(para)
    if not raw:
        return []
    # Then merge tokens when previous token ends with known abbreviation
    merged: List[str] = []
    for token in raw:
        token = token.strip()
        if not token:
            continue
        if merged and _ends_with_abbrev(merged[-1]):
            merged[-1] = (merged[-1].rstrip() + " " + token.lstrip())
        else:
            merged.append(token)
    return merged

def word_count(s: str) -> int:
    return len(WORD_RE.findall(s))

def has_metric_nearby(s: str) -> bool:
    return bool(METRIC_RE.search(s))

def normalize(s: str) -> str:
    return " ".join(s.lower().split())

def collect_banned(cfg: Dict[str, Any]) -> List[str]:
    banned = list(cfg.get("lint", {}).get("banned_phrases", []))
    forb = cfg.get("forbidden", {})
    if isinstance(forb.get("клише"), list):
        banned.extend(forb["клише"])
    lex = forb.get("лексика")
    if isinstance(lex, list):
        for item in lex:
            if isinstance(item, str):
                banned.append(item)
            elif isinstance(item, list):
                banned.extend(item)
    # de-dup & normalize
    seen, out = set(), []
    for p in banned:
        key = normalize(p)
        if key and key not in seen:
            out.append(p)
            seen.add(key)
    return out

def _is_excluded(path: Path, excludes: List[str], root: Path) -> bool:
    abs_path = path.resolve()
    try:
        rel = str(abs_path.relative_to(root))
    except ValueError:
        rel = str(abs_path)
    # check file path and parents against patterns
    for pat in excludes:
        if fnmatch.fnmatch(rel, pat):
            return True
    for parent in abs_path.parents:
        try:
            relp = str(parent.relative_to(root))
        except ValueError:
            relp = str(parent)
        for pat in excludes:
            if fnmatch.fnmatch(relp, pat) or fnmatch.fnmatch(relp + "/", pat):
                return True
    return False

def check_file(path: Path, cfg: Dict[str, Any],
               sr: Tuple[int,int], max_sent_len: int, max_para_sents: int,
               passive_allowed: bool, require_metrics: bool) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    paragraphs = split_paragraphs(text)
    banned = collect_banned(cfg)
    banned_norm = [normalize(p) for p in banned]

    issues: List[Dict[str, Any]] = []
    for pi, para in enumerate(paragraphs, 1):
        sents = split_sentences(para)
        if len(sents) > max_para_sents:
            issues.append({"level":"WARN","type":"paragraph_len","para":pi,
                           "msg":f"В абзаце {len(sents)} предложений (макс {max_para_sents})."})
        # banned phrases
        norm_para = normalize(para)
        for phrase, pnorm in zip(banned, banned_norm):
            if pnorm and pnorm in norm_para:
                issues.append({"level":"ERROR","type":"banned","para":pi,
                               "msg":f"Запрещённая фраза: '{phrase}'"})

        # sentence-level checks
        for si, s in enumerate(sents, 1):
            wc = word_count(s)
            if wc > max_sent_len:
                issues.append({"level":"WARN","type":"sentence_len","para":pi,"sent":si,
                               "msg":f"{wc} слов (макс {max_sent_len})."})
            elif wc < sr[0] or wc > sr[1]:
                issues.append({"level":"INFO","type":"sentence_target","para":pi,"sent":si,
                               "msg":f"{wc} слов (целевой диапазон {sr[0]}–{sr[1]})."})
            if not passive_allowed and PASSIVE_RE.search(s):
                issues.append({"level":"WARN","type":"passive","para":pi,"sent":si,
                               "msg":"Подозрение на пассивный залог."})
            if require_metrics and VAGUE_RE.search(s) and not has_metric_nearby(s):
                issues.append({"level":"WARN","type":"vague_no_metric","para":pi,"sent":si,
                               "msg":"Оценка без метрики рядом."})
            if re.search(r"\brouter\b", s, re.IGNORECASE):
                issues.append({"level":"INFO","type":"terminology","para":pi,"sent":si,
                               "msg":"Используй 'рутер' из глоссария."})

    found_terms = {t: (t.lower() in text.lower()) for t in TERMINOLOGY_KEYS}
    return {"file": str(path), "issues": issues, "term_coverage": found_terms}

def render_md(results: List[Dict[str, Any]]) -> Tuple[str, int]:
    lines = ["# Style Lint Report\n"]
    total_err = 0
    for r in results:
        lines.append(f"## {r['file']}")
        if not r["issues"]:
            lines.append("✔ Без замечаний.\n")
            continue
        for it in r["issues"]:
            if it["level"] == "ERROR":
                total_err += 1
            loc = []
            if "para" in it: loc.append(f"абз. {it['para']}")
            if "sent" in it: loc.append(f"предл. {it['sent']}")
            where = (" ("+", ".join(loc)+")") if loc else ""
            lines.append(f"- **{it['level']}**{where}: {it['msg']}")
        missing = [k for k,v in r["term_coverage"].items() if not v]
        if missing:
            lines.append("")
            lines.append("_Подсказка_: не встречаются базовые термины: " + ", ".join(missing))
        lines.append("")
    return "\n".join(lines), total_err

def safe_autofix(path: Path) -> None:
    # Only whitespace fixes
    txt = path.read_text(encoding="utf-8", errors="ignore")
    txt = re.sub(r"[ \t]+$", "", txt, flags=re.MULTILINE)       # strip trailing spaces
    txt = re.sub(r"\n{3,}", "\n\n", txt)                        # collapse >2 blank lines
    path.write_text(txt, encoding="utf-8")

def iter_targets(args: argparse.Namespace) -> List[Path]:
    files: List[Path] = []
    globs = []
    if args.glob:
        globs = [args.glob]
    else:
        globs = ["**/*.md", "**/*.txt"]

    excludes = list(DEFAULT_EXCLUDES)
    if args.exclude:
        excludes.extend(args.exclude)

    inputs = (args.paths or ["." ])
    for a in inputs:
        p = Path(a)
        if p.is_file():
            if not _is_excluded(p, excludes, ROOT):
                files.append(p)
        elif p.is_dir():
            for g in globs:
                for f in p.rglob(g):
                    if f.is_file() and not _is_excluded(f, excludes, ROOT):
                        files.append(f)

    uniq = sorted({f.resolve() for f in files})
    return [Path(u) for u in uniq]

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="*", help="Files or directories")
    parser.add_argument("--json", dest="json_out", help="Save JSON report to path")
    parser.add_argument("--fix", action="store_true", help="Apply safe autofix (whitespace only)")
    parser.add_argument("--glob", help="Glob pattern within dirs, default=**/*.md and **/*.txt")
    parser.add_argument("--exclude", action="append", help="Exclude glob; can be repeated")
    parser.add_argument("--max-sent", type=int, help="Max sentence length override")
    parser.add_argument("--target-len", help="Target sentence len range A,B")
    parser.add_argument("--max-para", type=int, help="Max sentences per paragraph override")
    parser.add_argument("--passive-allow", action="store_true", help="Allow passive voice")
    parser.add_argument("--require-metrics", type=int, choices=[0,1], help="Require metrics near vague claims")
    return parser.parse_args()

def main() -> int:
    args = parse_args()
    cfg = load_cfg()

    lint_cfg = cfg.get("lint", {})
    max_sent_len = int(args.max_sent or lint_cfg.get("max_sentence_len", 22))
    target_lo, target_hi = (lint_cfg.get("target_sentence_len", [8, 16]))
    if args.target_len:
        a,b = args.target_len.split(",")
        target_lo, target_hi = int(a), int(b)
    max_para_sents = int(args.max_para or lint_cfg.get("max_paragraph_sentences", 5))
    passive_allowed = bool(args.passive_allow or lint_cfg.get("passive_voice_allowed", False))
    require_metrics = bool(
        (lint_cfg.get("require_metrics_for_claims", True)) if args.require_metrics is None
        else args.require_metrics == 1
    )

    targets = iter_targets(args)
    if not targets:
        print("[ERR] No .md/.txt files found.", file=sys.stderr)
        return 2

    results = []
    for p in targets:
        if args.fix:
            safe_autofix(p)
        results.append(check_file(
            p, cfg,
            (target_lo, target_hi), max_sent_len, max_para_sents,
            passive_allowed, require_metrics
        ))

    md, total_err = render_md(results)
    print(md)

    if args.json_out:
        Path(args.json_out).write_text(json.dumps({"results": results}, ensure_ascii=False, indent=2), encoding="utf-8")

    return 1 if total_err else 0

if __name__ == "__main__":
    raise SystemExit(main())
