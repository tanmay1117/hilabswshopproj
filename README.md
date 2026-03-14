# HiLabs Workshop — Clinical AI Evaluation Framework

Evaluation and reliability layer for a clinical AI entity extraction pipeline.

## Repository Structure

```
.
├── test.py             # Main evaluator (required entry point)
├── run_all.py          # Batch runner for all 30 charts
├── generate_report.py  # Aggregates output/ → report.md
├── output/             # Per-chart evaluation JSONs (generated)
└── report.md           # Summary report (generated)
```

---

## Quick Start

### 1. Install dependencies

```bash
pip install requests
```

### 2. Set your OpenRouter API key

```bash
export OPENROUTER_API_KEY="sk-or-..."
```

### 3. Evaluate a single chart

```bash
python test.py path/to/chart.json output/chart.json
```

The `.md` file is auto-detected in the same folder as the JSON.
You can also pass it explicitly:

```bash
python test.py path/to/chart.json output/chart.json --md path/to/chart.md
```

### 4. Evaluate all 30 charts

```bash
python run_all.py --data-dir workshop_test_data --output-dir output
```

### 5. Generate the report

```bash
python generate_report.py --output-dir output --report report.md
```

---

## Evaluation Methodology

### LLM-as-Judge (OpenRouter · qwen/qwen3-coder-32b:free)

For each chart, up to **5 entities per entity type** (≈50 entities total) are
sampled and sent to the LLM in batches of 8. The LLM is asked to judge whether
the following labels are correct given the clinical context:

| Dimension      | Values checked                                      |
|----------------|-----------------------------------------------------|
| `entity_type`  | MEDICINE, PROBLEM, PROCEDURE, TEST, VITAL_NAME, … |
| `assertion`    | POSITIVE, NEGATIVE, UNCERTAIN                       |
| `temporality`  | CURRENT, CLINICAL_HISTORY, UPCOMING, UNCERTAIN      |
| `subject`      | PATIENT, FAMILY_MEMBER                              |

Error rates are computed per label value and reported as fractions (0–1).

### Heuristic Checks (all entities)

| Check                     | Method                                                   |
|---------------------------|----------------------------------------------------------|
| Empty field errors        | Entities with null assertion/temporality/subject flagged |
| Event date accuracy       | Extracted ISO dates matched against MM/DD/YY in source   |
| Attribute completeness    | Expected metadata (DOSE/ROUTE/FREQ for meds, etc.)       |

### Output JSON Schema

```json
{
  "file_name": "string",
  "entity_type_error_rate": { "MEDICINE": 0.0, "PROBLEM": 0.0, ... },
  "assertion_error_rate":   { "POSITIVE": 0.0, "NEGATIVE": 0.0, "UNCERTAIN": 0.0 },
  "temporality_error_rate": { "CURRENT": 0.0, "CLINICAL_HISTORY": 0.0, "UPCOMING": 0.0, "UNCERTAIN": 0.0 },
  "subject_error_rate":     { "PATIENT": 0.0, "FAMILY_MEMBER": 0.0 },
  "event_date_accuracy":    0.0,
  "attribute_completeness": 0.0
}
```

---

## Key Findings

1. **FAMILY_MEMBER subject never assigned** — entities with family history context
   are consistently tagged as `PATIENT`, conflating hereditary risk factors with
   active patient conditions.

2. **Negation / Uncertainty errors** — NEGATIVE and UNCERTAIN assertions have the
   highest error rates; the pipeline tends to over-predict POSITIVE.

3. **CLINICAL_HISTORY mis-classification** — the pipeline under-uses historical
   temporality, defaulting to CURRENT even in past-history sections.

4. **PROCEDURE / SDOH boundary confusion** — these entity types share the highest
   mis-classification rates due to overlapping clinical language.

5. **PHI-redacted date accuracy** — most dates in source MDs are replaced by
   `[ENCOUNTER_DATE]` placeholders; low date accuracy partly reflects
   the redaction pipeline, not purely extraction error.

6. **Attribute completeness ~50%** — MEDICINE entities frequently lack FREQUENCY;
   TEST entities lack TEST_UNIT, limiting downstream pharmacological reasoning.

---

## Model & API

- **Provider**: [OpenRouter](https://openrouter.ai)
- **Model**: `qwen/qwen3-coder-32b:free`
- **Endpoint**: `https://openrouter.ai/api/v1/chat/completions`
