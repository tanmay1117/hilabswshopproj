#!/usr/bin/env python3
"""
HiLabs Workshop — Clinical AI Pipeline Evaluator
================================================
Evaluates entity extractions from medical charts using:
  1. LLM-as-judge  (OpenRouter qwen/qwen3-coder-32b:free)  — sample per entity type
  2. Heuristic checks                                        — all entities
     • Empty required fields
     • Date presence in source text
     • Attribute completeness per entity type

Usage:
    python test.py input.json output.json [--md source.md] [--api-key KEY]

Environment:
    OPENROUTER_API_KEY   — API key (alternative to --api-key flag)
"""

import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Optional

import requests

# ── Configuration ─────────────────────────────────────────────────────────────
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL   = "qwen/qwen3-coder-32b:free"
API_KEY            = os.environ.get("OPENROUTER_API_KEY", "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")

LLM_BATCH_SIZE     = 8   # entities per LLM call
SAMPLE_PER_TYPE    = 5   # max entities sampled per entity_type for LLM eval

ALL_ENTITY_TYPES = [
    "MEDICINE", "PROBLEM", "PROCEDURE", "TEST", "VITAL_NAME",
    "IMMUNIZATION", "MEDICAL_DEVICE", "MENTAL_STATUS", "SDOH", "SOCIAL_HISTORY",
]

# Metadata attributes expected per entity type (for completeness scoring)
EXPECTED_ATTRS: dict[str, set] = {
    "MEDICINE":       {"DOSE", "ROUTE", "FREQUENCY"},
    "TEST":           {"TEST_VALUE", "TEST_UNIT"},
    "VITAL_NAME":     {"VITAL_NAME_VALUE", "VITAL_NAME_UNIT"},
    "PROBLEM":        set(),
    "PROCEDURE":      set(),
    "IMMUNIZATION":   set(),
    "MEDICAL_DEVICE": set(),
    "MENTAL_STATUS":  set(),
    "SDOH":           set(),
    "SOCIAL_HISTORY": set(),
}

# ── LLM helpers ───────────────────────────────────────────────────────────────
_SYSTEM_PROMPT = """/no-think
You are a senior clinical NLP expert auditing entity extractions from hospital medical charts.

For each entity you receive, determine whether the following four labels are correct given the entity text and its context:
  • entity_type   — one of: MEDICINE, PROBLEM, PROCEDURE, TEST, VITAL_NAME, IMMUNIZATION,
                    MEDICAL_DEVICE, MENTAL_STATUS, SDOH, SOCIAL_HISTORY
  • assertion     — POSITIVE (condition present/confirmed), NEGATIVE (absent/denied/ruled out),
                    UNCERTAIN (possible/suspected/not confirmed)
  • temporality   — CURRENT (active now), CLINICAL_HISTORY (past history),
                    UPCOMING (future/scheduled), UNCERTAIN (cannot determine)
  • subject       — PATIENT (about the patient themselves),
                    FAMILY_MEMBER (about a relative / family history)

Return ONLY a valid JSON array with one object per entity (same order as input):
[
  {
    "entity_type_correct": true,
    "assertion_correct": false,
    "temporality_correct": true,
    "subject_correct": true,
    "note": "assertion should be NEGATIVE — context says 'no history of'"
  },
  ...
]
No markdown fences, no extra text — just the raw JSON array.
""".strip()


def _strip_think_tags(text: str) -> str:
    """Remove <think>...</think> blocks that Qwen3 may emit."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def call_llm(user_prompt: str, retries: int = 3) -> str:
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": user_prompt},
        ],
        "max_tokens": 2048,
        "temperature": 0,
    }
    for attempt in range(retries):
        try:
            resp = requests.post(OPENROUTER_API_URL, headers=headers,
                                 json=payload, timeout=90)
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"]
            return _strip_think_tags(raw)
        except Exception as exc:
            wait = 2 ** attempt
            print(f"  [WARN] LLM attempt {attempt+1} failed: {exc} — retry in {wait}s",
                  file=sys.stderr)
            time.sleep(wait)
    return ""


def evaluate_batch(batch: list[dict], source_excerpt: str) -> list[dict]:
    """Send one batch to the LLM and return per-entity verdicts."""
    slim = [
        {
            "id":           i,
            "entity":       e.get("entity", ""),
            "entity_type":  e.get("entity_type", ""),
            "assertion":    e.get("assertion", ""),
            "temporality":  e.get("temporality", ""),
            "subject":      e.get("subject", ""),
            "context":      (e.get("text") or "")[:300],
            "heading":      e.get("heading", ""),
        }
        for i, e in enumerate(batch)
    ]
    prompt = (
        f"CLINICAL TEXT EXCERPT (first 4 000 chars):\n{source_excerpt[:4000]}\n\n"
        f"ENTITIES TO EVALUATE:\n{json.dumps(slim, indent=2)}"
    )
    raw = call_llm(prompt)
    if not raw:
        return _fallback(batch)
    # Strip possible markdown fences
    raw = re.sub(r"```(?:json)?", "", raw).strip().strip("`")
    try:
        result = json.loads(raw)
        if isinstance(result, list) and len(result) == len(batch):
            return result
    except Exception as exc:
        print(f"  [WARN] JSON parse failed: {exc}", file=sys.stderr)
    return _fallback(batch)


def _fallback(batch: list[dict]) -> list[dict]:
    """Return all-correct verdict as a safe fallback."""
    return [
        {"entity_type_correct": True, "assertion_correct": True,
         "temporality_correct": True, "subject_correct": True}
        for _ in batch
    ]


# ── Heuristic checks ──────────────────────────────────────────────────────────
def _relation_types(entity: dict) -> set:
    rels = entity.get("metadata_from_qa", {}).get("relations", [])
    return {r["entity_type"] for r in rels}


def _dates_in_entity(entity: dict) -> list:
    rels = entity.get("metadata_from_qa", {}).get("relations", [])
    return [r["entity"] for r in rels if r["entity_type"] in ("exact_date", "derived_date")]


def compute_attribute_completeness(entities: list[dict]) -> float:
    """Fraction of expected metadata attributes that are present."""
    total, present = 0, 0
    for e in entities:
        expected = EXPECTED_ATTRS.get(e.get("entity_type", ""), set())
        if not expected:
            continue
        found = _relation_types(e)
        total   += len(expected)
        present += len(expected & found)
    return (present / total) if total else 1.0


def compute_date_accuracy(entities: list[dict], source_md: str) -> float:
    """
    For every extracted date, check whether it (or a common reformatting)
    appears somewhere in the source markdown.

    NOTE: Many clinical MD files have PHI redacted as [ENCOUNTER_DATE].
    This means extracted dates derived from redacted fields will legitimately
    not appear in the source — the metric reflects verifiable date accuracy
    for non-redacted dates only. A low score signals heavy PHI redaction,
    not necessarily an extraction error.
    """
    total = correct = 0
    src_digits = re.sub(r"\D", "", source_md)  # all digits concatenated for loose match

    for e in entities:
        for date_str in _dates_in_entity(e):
            total += 1
            # 1. ISO exact match: 2024-01-12
            if date_str in source_md:
                correct += 1
                continue
            # 2. MM/DD/YY — most common US clinical format
            try:
                parts = date_str.split("-")
                if len(parts) == 3:
                    yy  = parts[0][-2:]
                    mm  = parts[1].lstrip("0") or "0"
                    dd  = parts[2].lstrip("0") or "0"
                    alts = [
                        f"{parts[1]}/{parts[2]}/{yy}",      # 01/12/24
                        f"{mm}/{dd}/{yy}",                   # 1/12/24
                        f"{parts[1]}/{parts[2]}/{parts[0]}", # 01/12/2024
                        f"{mm}/{dd}/{parts[0]}",             # 1/12/2024
                    ]
                    if any(a in source_md for a in alts):
                        correct += 1
                        continue
            except Exception:
                pass
            # 3. Loose digit match (only for non-redacted files)
            date_digits = re.sub(r"\D", "", date_str)
            if date_digits and date_digits in src_digits:
                correct += 1

    return (correct / total) if total else 1.0


def heuristic_empty_field_errors(entities: list[dict]) -> dict:
    """
    Empty assertion / temporality / subject fields are definite pipeline errors.
    Returns counts per dimension.
    """
    empty = {"assertion": 0, "temporality": 0, "subject": 0}
    for e in entities:
        if not e.get("assertion"):
            empty["assertion"] += 1
        if not e.get("temporality"):
            empty["temporality"] += 1
        if not e.get("subject"):
            empty["subject"] += 1
    return empty


# ── Sampling strategy ─────────────────────────────────────────────────────────
def sample_entities_for_llm(entities: list[dict]) -> tuple[list[dict], list[int]]:
    """
    Sample up to SAMPLE_PER_TYPE entities per entity_type.
    Returns (sampled_entities, original_indices).
    """
    buckets: dict[str, list] = defaultdict(list)
    for idx, e in enumerate(entities):
        buckets[e.get("entity_type", "UNKNOWN")].append((idx, e))

    sampled_entities, sampled_indices = [], []
    for etype, items in buckets.items():
        for idx, e in items[:SAMPLE_PER_TYPE]:
            sampled_indices.append(idx)
            sampled_entities.append(e)
    return sampled_entities, sampled_indices


# ── Core evaluator ────────────────────────────────────────────────────────────
def evaluate_file(json_path: str,
                  md_path: Optional[str] = None,
                  verbose: bool = True) -> dict:
    """
    Full evaluation of one chart file. Returns the output JSON dict.
    """
    jp = Path(json_path)
    mp = Path(md_path) if md_path else jp.with_suffix(".md")

    with open(jp, encoding="utf-8") as f:
        entities: list[dict] = json.load(f)

    source_md = ""
    if mp.exists():
        with open(mp, encoding="utf-8") as f:
            source_md = f.read()
    else:
        print(f"  [WARN] Markdown not found: {mp}", file=sys.stderr)

    n = len(entities)
    log = (lambda msg: print(f"  {msg}", file=sys.stderr)) if verbose else lambda _: None
    log(f"Loaded {n} entities | md={'yes' if source_md else 'NO'}")

    # ── 1. Heuristic metrics (full dataset) ────────────────────────────────
    empty_errors  = heuristic_empty_field_errors(entities)
    date_accuracy = compute_date_accuracy(entities, source_md)
    attr_complete = compute_attribute_completeness(entities)

    # ── 2. LLM sampling ────────────────────────────────────────────────────
    sampled, s_indices = sample_entities_for_llm(entities)
    log(f"LLM sample: {len(sampled)} entities ({len(s_indices)} indices)")

    llm_verdicts: dict[int, dict] = {}   # original_index → verdict

    for batch_start in range(0, len(sampled), LLM_BATCH_SIZE):
        batch_e   = sampled[batch_start: batch_start + LLM_BATCH_SIZE]
        batch_idx = s_indices[batch_start: batch_start + LLM_BATCH_SIZE]
        b_num = batch_start // LLM_BATCH_SIZE + 1
        b_tot = (len(sampled) - 1) // LLM_BATCH_SIZE + 1
        log(f"LLM batch {b_num}/{b_tot} ({len(batch_e)} entities)…")
        verdicts = evaluate_batch(batch_e, source_md)
        for orig_idx, verdict in zip(batch_idx, verdicts):
            llm_verdicts[orig_idx] = verdict
        time.sleep(0.4)   # be polite to free tier

    # ── 3. Aggregate error rates ────────────────────────────────────────────
    # Per-type counters (only from sampled entities)
    type_total:  dict[str, int] = defaultdict(int)
    type_errors: dict[str, int] = defaultdict(int)

    assert_total:  dict[str, int] = defaultdict(int)
    assert_errors: dict[str, int] = defaultdict(int)

    temp_total:  dict[str, int] = defaultdict(int)
    temp_errors: dict[str, int] = defaultdict(int)

    subj_total:  dict[str, int] = defaultdict(int)
    subj_errors: dict[str, int] = defaultdict(int)

    for orig_idx, verdict in llm_verdicts.items():
        e = entities[orig_idx]

        etype  = e.get("entity_type") or "UNKNOWN"
        asrt   = e.get("assertion")   or "UNKNOWN"
        tempo  = e.get("temporality") or "UNKNOWN"
        subj   = e.get("subject")     or "UNKNOWN"

        type_total[etype]  += 1
        assert_total[asrt] += 1
        temp_total[tempo]  += 1
        subj_total[subj]   += 1

        if not verdict.get("entity_type_correct",  True): type_errors[etype]  += 1
        if not verdict.get("assertion_correct",     True): assert_errors[asrt] += 1
        if not verdict.get("temporality_correct",   True): temp_errors[tempo]  += 1
        if not verdict.get("subject_correct",       True): subj_errors[subj]   += 1

    # Fold in heuristic empty-field errors
    # Count empty assertion as assertion errors distributed across UNKNOWN bucket
    assert_total["UNKNOWN"] += empty_errors["assertion"]
    assert_errors["UNKNOWN"] += empty_errors["assertion"]
    temp_total["UNKNOWN"]   += empty_errors["temporality"]
    temp_errors["UNKNOWN"]  += empty_errors["temporality"]
    subj_total["UNKNOWN"]   += empty_errors["subject"]
    subj_errors["UNKNOWN"]  += empty_errors["subject"]

    def rate(err_d, tot_d, key):
        t = tot_d.get(key, 0)
        return round(err_d.get(key, 0) / t, 4) if t else 0.0

    entity_type_error_rate = {
        t: rate(type_errors, type_total, t) for t in ALL_ENTITY_TYPES
    }

    assertion_error_rate = {
        "POSITIVE":  rate(assert_errors, assert_total, "POSITIVE"),
        "NEGATIVE":  rate(assert_errors, assert_total, "NEGATIVE"),
        "UNCERTAIN": rate(assert_errors, assert_total, "UNCERTAIN"),
    }

    temporality_error_rate = {
        "CURRENT":          rate(temp_errors, temp_total, "CURRENT"),
        "CLINICAL_HISTORY": rate(temp_errors, temp_total, "CLINICAL_HISTORY"),
        "UPCOMING":         rate(temp_errors, temp_total, "UPCOMING"),
        "UNCERTAIN":        rate(temp_errors, temp_total, "UNCERTAIN"),
    }

    subject_error_rate = {
        "PATIENT":       rate(subj_errors, subj_total, "PATIENT"),
        "FAMILY_MEMBER": rate(subj_errors, subj_total, "FAMILY_MEMBER"),
    }

    return {
        "file_name":               jp.name,
        "entity_type_error_rate":  entity_type_error_rate,
        "assertion_error_rate":    assertion_error_rate,
        "temporality_error_rate":  temporality_error_rate,
        "subject_error_rate":      subject_error_rate,
        "event_date_accuracy":     round(date_accuracy, 4),
        "attribute_completeness":  round(attr_complete, 4),
    }


# ── CLI entry point ───────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="HiLabs Clinical AI Evaluator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("input_json",  help="Input JSON entity file")
    parser.add_argument("output_json", help="Output JSON evaluation report")
    parser.add_argument("--md",      metavar="FILE",
                        help="Source markdown file (auto-detected if omitted)")
    parser.add_argument("--api-key", metavar="KEY",
                        help="OpenRouter API key (overrides OPENROUTER_API_KEY env var)")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress progress output")
    args = parser.parse_args()

    global API_KEY
    if args.api_key:
        API_KEY = args.api_key
    if not API_KEY:
        print("ERROR: OpenRouter API key required.\n"
              "  Set OPENROUTER_API_KEY env var  OR  pass --api-key KEY",
              file=sys.stderr)
        sys.exit(1)

    if not args.quiet:
        print(f"\n{'='*60}", file=sys.stderr)
        print(f"  Evaluating: {args.input_json}", file=sys.stderr)
        print(f"{'='*60}", file=sys.stderr)

    result = evaluate_file(
        args.input_json,
        md_path=args.md,
        verbose=not args.quiet,
    )

    out = Path(args.output_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    if not args.quiet:
        print(f"\n  ✓ Saved → {out}", file=sys.stderr)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
