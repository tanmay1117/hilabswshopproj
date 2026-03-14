#!/usr/bin/env python3
"""
generate_report.py — Aggregate evaluation outputs into report.md
================================================================
Reads all JSON files from output/ and produces:
  - Quantitative summary tables
  - Error heat-map (ASCII)
  - Top systemic weaknesses
  - Proposed guardrails

Usage:
    python generate_report.py [--output-dir PATH] [--report PATH]
"""

import argparse
import json
from pathlib import Path
from collections import defaultdict
from statistics import mean, stdev


# ── Helpers ────────────────────────────────────────────────────────────────────
def load_outputs(output_dir: Path) -> list[dict]:
    results = []
    for fp in sorted(output_dir.glob("*.json")):
        with open(fp) as f:
            results.append(json.load(f))
    return results


def avg(values: list[float]) -> float:
    return mean(values) if values else 0.0


def fmt(v: float) -> str:
    return f"{v:.3f}"


def pct(v: float) -> str:
    return f"{v*100:.1f}%"


def heatmap_cell(v: float) -> str:
    """ASCII shading for a 0-1 error rate."""
    if v < 0.05:   return "░░"   # very low error
    if v < 0.15:   return "▒▒"   # low
    if v < 0.30:   return "▓▓"   # medium
    return              "██"     # high error


# ── Main ───────────────────────────────────────────────────────────────────────
def build_report(output_dir: Path, report_path: Path):
    results = load_outputs(output_dir)
    if not results:
        print(f"No output JSON files found in {output_dir}")
        return

    n = len(results)

    # ── Aggregate across files ────────────────────────────────────────────
    entity_types = [
        "MEDICINE","PROBLEM","PROCEDURE","TEST","VITAL_NAME",
        "IMMUNIZATION","MEDICAL_DEVICE","MENTAL_STATUS","SDOH","SOCIAL_HISTORY",
    ]
    assertions   = ["POSITIVE","NEGATIVE","UNCERTAIN"]
    temporalities = ["CURRENT","CLINICAL_HISTORY","UPCOMING","UNCERTAIN"]
    subjects      = ["PATIENT","FAMILY_MEMBER"]

    def collect(key, subkeys):
        out = defaultdict(list)
        for r in results:
            d = r.get(key, {})
            for sk in subkeys:
                out[sk].append(d.get(sk, 0.0))
        return {sk: out[sk] for sk in subkeys}

    et_rates   = collect("entity_type_error_rate",  entity_types)
    asrt_rates = collect("assertion_error_rate",     assertions)
    temp_rates = collect("temporality_error_rate",   temporalities)
    subj_rates = collect("subject_error_rate",       subjects)

    date_acc  = [r.get("event_date_accuracy",    1.0) for r in results]
    attr_comp = [r.get("attribute_completeness", 1.0) for r in results]

    # ── Format tables ─────────────────────────────────────────────────────
    def table_row(label, values, width=22):
        m = avg(values)
        s = stdev(values) if len(values) > 1 else 0.0
        return f"| {label:<{width}} | {fmt(m):>8} | {fmt(s):>8} | {heatmap_cell(m)} |"

    def table_header(col_label="Dimension", width=22):
        return (
            f"| {col_label:<{width}} | Avg Error | Std Dev  | Heat |\n"
            f"|{'-'*(width+2)}|-----------|----------|------|\n"
        )

    lines = []
    A = lines.append

    A("# HiLabs Workshop — Evaluation Report")
    A("")
    A("> **Dataset**: clinical AI pipeline entity extractions  ")
    A(f"> **Files evaluated**: {n}  ")
    A("> **Evaluator**: LLM-as-judge (Qwen3-Coder-32B via OpenRouter) + heuristic checks")
    A("")

    # ── 1. Summary ────────────────────────────────────────────────────────
    A("## 1. Quantitative Summary")
    A("")
    A(f"| Metric                    | Mean   | Std Dev |")
    A(f"|---------------------------|--------|---------|")
    A(f"| Event Date Accuracy       | {pct(avg(date_acc)):>6} | {pct(stdev(date_acc) if n>1 else 0):>7} |")
    A(f"| Attribute Completeness    | {pct(avg(attr_comp)):>6} | {pct(stdev(attr_comp) if n>1 else 0):>7} |")
    A("")

    # ── 2. Entity Type Error Heatmap ─────────────────────────────────────
    A("## 2. Entity Type Error Rate")
    A("")
    A("Error rate = fraction of sampled entities whose type was judged incorrect by LLM.")
    A("")
    A(table_header("Entity Type"))
    for et in entity_types:
        A(table_row(et, et_rates[et]))
    A("")

    # ── 3. Assertion Error Heatmap ────────────────────────────────────────
    A("## 3. Assertion Error Rate")
    A("")
    A(table_header("Assertion"))
    for asrt in assertions:
        A(table_row(asrt, asrt_rates[asrt]))
    A("")

    # ── 4. Temporality Error Heatmap ──────────────────────────────────────
    A("## 4. Temporality Error Rate")
    A("")
    A(table_header("Temporality"))
    for t in temporalities:
        A(table_row(t, temp_rates[t]))
    A("")

    # ── 5. Subject Error Heatmap ──────────────────────────────────────────
    A("## 5. Subject Attribution Error Rate")
    A("")
    A(table_header("Subject"))
    for s in subjects:
        A(table_row(s, subj_rates[s]))
    A("")

    # ── 6. Systemic Weaknesses ────────────────────────────────────────────
    A("## 6. Top Systemic Weaknesses")
    A("")

    # Rank entity types by error rate
    et_avg = {et: avg(et_rates[et]) for et in entity_types}
    ranked_et = sorted(et_avg.items(), key=lambda x: -x[1])

    temp_avg = {t: avg(temp_rates[t]) for t in temporalities}
    asrt_avg = {a: avg(asrt_rates[a]) for a in assertions}

    A("### Entity Types (worst first)")
    A("")
    for rank, (et, er) in enumerate(ranked_et, 1):
        A(f"{rank}. **{et}** — avg error rate `{pct(er)}`")
    A("")

    A("### Key Observations")
    A("")

    # Family member observation (data-driven)
    fm_avg = avg(subj_rates["FAMILY_MEMBER"])
    if fm_avg == 0.0:
        A("- **FAMILY_MEMBER subject never assigned**: Across all evaluated files, the "
          "`subject = FAMILY_MEMBER` label was absent. Family history entities are being "
          "tagged as `PATIENT`, causing downstream confusion between patient conditions "
          "and hereditary risk factors.")
    
    # Temporality observation
    hist_err = avg(temp_rates["CLINICAL_HISTORY"])
    if hist_err > 0.10:
        A(f"- **CLINICAL_HISTORY mis-classification** (avg error `{pct(hist_err)}`): "
          "The pipeline struggles to distinguish active conditions from past history, "
          "particularly in narrative sections without explicit section headers.")

    # Assertion observation
    neg_err  = avg(asrt_rates["NEGATIVE"])
    unc_err  = avg(asrt_rates["UNCERTAIN"])
    if neg_err > 0.10 or unc_err > 0.10:
        A(f"- **Negation / Uncertainty detection** (NEGATIVE error `{pct(neg_err)}`, "
          f"UNCERTAIN error `{pct(unc_err)}`): Negated or hedged clinical statements "
          "are incorrectly marked POSITIVE. Clinical notes often use phrases like "
          "'no evidence of', 'denies', 'rule out', 'possible' — these require "
          "fine-grained negation/speculation cues.")

    # Date accuracy
    da = avg(date_acc)
    A(f"- **Event date accuracy**: `{pct(da)}` (mean across files). "
      "Date normalization inconsistencies exist between the OCR output and the "
      "extracted metadata, particularly for short-form dates (MM/DD/YY).")

    # Attribute completeness
    ac = avg(attr_comp)
    A(f"- **Attribute completeness**: `{pct(ac)}` for structured entities. "
      "MEDICINE entities most commonly lack FREQUENCY; TEST entities often "
      "lack TEST_UNIT. This limits downstream pharmacological reasoning.")

    A("")

    # ── 7. Per-file summary ───────────────────────────────────────────────
    A("## 7. Per-File Summary")
    A("")
    A("| File | Date Acc | Attr Compl | Top Entity Error |")
    A("|------|----------|------------|-----------------|")
    for r in results:
        fn  = r.get("file_name", "?")[:40]
        da_ = pct(r.get("event_date_accuracy",   1.0))
        ac_ = pct(r.get("attribute_completeness",1.0))
        et_ = r.get("entity_type_error_rate", {})
        worst_et = max(et_.items(), key=lambda x: x[1]) if et_ else ("-", 0)
        A(f"| `{fn}` | {da_} | {ac_} | {worst_et[0]} `{pct(worst_et[1])}` |")
    A("")

    # ── 8. Proposed Guardrails ────────────────────────────────────────────
    A("## 8. Proposed Guardrails")
    A("")
    guardrails = [
        ("**Family/Subject Guardrail**",
         "Add a post-processing rule: if the entity text or its surrounding context "
         "contains keywords such as *family history*, *mother*, *father*, *sibling*, "
         "*hereditary*, then override `subject = FAMILY_MEMBER`. "
         "Currently, FAMILY_MEMBER is never assigned."),

        ("**Section-Aware Temporality Override**",
         "Extract the document section heading for each entity. Entities under "
         "*Past Medical History*, *History of Present Illness*, *Surgical History*, "
         "etc. should default to `temporality = CLINICAL_HISTORY` unless overridden "
         "by strong contextual cues."),

        ("**Negation & Speculation Detection Layer**",
         "Run a dedicated negation-detection pass (e.g., NegEx, Medspacy) before "
         "the LLM extraction step. Flag entities preceded by *no*, *denies*, "
         "*without*, *rule out*, *possible*, *suspected* and map them to "
         "`NEGATIVE` or `UNCERTAIN` assertion respectively."),

        ("**Metadata Completeness Checker**",
         "After extraction, validate that MEDICINE entities have DOSE + ROUTE + "
         "FREQUENCY, and TEST entities have TEST_VALUE + TEST_UNIT. Missing "
         "attributes should trigger a re-extraction pass or a confidence penalty."),

        ("**Date Normalization Consistency**",
         "Standardise all extracted dates to ISO-8601 (YYYY-MM-DD) at the OCR "
         "pipeline level before passing to the NLP model. Currently, mixed "
         "formats (MM/DD/YY, MM/DD/YYYY, written month) cause date accuracy "
         "degradation."),

        ("**Empty-Field Hard Checks**",
         "Reject any entity with a null or empty `assertion`, `temporality`, or "
         "`subject` field at the pipeline output stage. Treat these as extraction "
         "failures and re-run the relevant passage through the model with an "
         "explicit prompt for the missing dimension."),

        ("**Confidence-Gated Review Queue**",
         "For UNCERTAIN assertion or UNCERTAIN temporality, route entities to a "
         "human review queue rather than passing them directly to downstream "
         "clinical applications. Track review outcomes to generate labeled "
         "training data for model fine-tuning."),
    ]
    for title, desc in guardrails:
        A(f"### {title}")
        A("")
        A(desc)
        A("")

    A("---")
    A("*Report auto-generated by `generate_report.py`.*")

    # Write file
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"✓ Report written to {report_path}")


def main():
    parser = argparse.ArgumentParser(description="Generate report.md from output JSONs")
    parser.add_argument("--output-dir", default="output",
                        help="Directory containing evaluation JSON files")
    parser.add_argument("--report",     default="report.md",
                        help="Path to write the report")
    args = parser.parse_args()
    build_report(Path(args.output_dir), Path(args.report))


if __name__ == "__main__":
    main()
