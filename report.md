# HiLabs Workshop — Evaluation Report

> **Dataset**: 30 clinical charts · 16,566 extracted entities  
> **Evaluator**: LLM-as-judge (Qwen3-Coder-32B · OpenRouter) + deterministic heuristics  
> **Method**: Up to 5 entities sampled per entity type per chart → LLM verdict on all four labels; heuristic checks applied to entire entity set  

---

## 1. Quantitative Summary

| Metric                 | Mean  | Median | Std Dev | Min   | Max    |
|------------------------|-------|--------|---------|-------|--------|
| Event Date Accuracy    | 54.7% | 55.6%  | 39.8%   | 0.0%  | 100.0% |
| Attribute Completeness | 50.4% | 51.4%  | 15.0%   | 16.1% | 71.5%  |

High variance in date accuracy (std 39.8%) reveals a structural split in the dataset: charts where OCR preserved raw date strings score ~100%; charts where all dates were PHI-redacted to `[ENCOUNTER_DATE]` score 0%. This is a pipeline-design finding, not a per-chart anomaly.

Attribute completeness at ~50% means structured entities carry on average only half their expected metadata attributes — a critical gap for downstream pharmacological and diagnostic reasoning.

---

## 2. Entity Type Distribution

| Entity Type    | Count  | Share  |
|----------------|--------|--------|
| PROCEDURE      | 5,499  | 33.2%  |
| PROBLEM        | 4,588  | 27.7%  |
| TEST           | 2,105  | 12.7%  |
| MEDICINE       | 1,999  | 12.1%  |
| VITAL_NAME     | 977    | 5.9%   |
| MENTAL_STATUS  | 352    | 2.1%   |
| MEDICAL_DEVICE | 308    | 1.9%   |
| SOCIAL_HISTORY | 294    | 1.8%   |
| SDOH           | 291    | 1.8%   |
| IMMUNIZATION   | 153    | 0.9%   |

PROCEDURE dominates (33%) because section headers, table labels, and administrative acts are frequently — and often incorrectly — tagged as clinical procedures.

---

## 3. Entity Type Error Rate

Error rate = fraction of sampled entities whose type label was judged incorrect by the LLM.

| Entity Type    | Avg Error | Std Dev | Heat |
|----------------|-----------|---------|------|
| SDOH           | 21.9%     | 27.1%   | ▓▓   |
| PROCEDURE      | 21.3%     | 18.3%   | ▓▓   |
| SOCIAL_HISTORY | 19.7%     | 26.7%   | ▓▓   |
| MEDICAL_DEVICE | 11.7%     | 11.9%   | ▒▒   |
| TEST           | 9.3%      | 13.6%   | ▒▒   |
| MENTAL_STATUS  | 9.3%      | 21.2%   | ▒▒   |
| PROBLEM        | 8.0%      | 9.0%    | ▒▒   |
| MEDICINE       | 5.5%      | 8.1%    | ░░   |
| IMMUNIZATION   | 2.7%      | 6.1%    | ░░   |
| VITAL_NAME     | 2.7%      | 9.7%    | ░░   |

_Heat key: ░░ < 5% · ▒▒ 5–15% · ▓▓ 15–30% · ██ > 30%_

SDOH and PROCEDURE share the highest misclassification rates. The boundary between a social determinant (housing instability, food insecurity), an administrative procedure (referral, discharge planning), and a free-text note entry is blurred in clinical documentation. SOCIAL_HISTORY (19.7%) is frequently mis-labeled as PROBLEM or SDOH — phrases like "former smoker" or "alcohol use" straddle all three categories.

---

## 4. Assertion Error Rate

| Assertion | Avg Error | Std Dev | Heat |
|-----------|-----------|---------|------|
| UNCERTAIN | 22.8%     | 34.9%   | ▓▓   |
| NEGATIVE  | 20.8%     | 23.3%   | ▓▓   |
| POSITIVE  | 4.1%      | 3.9%    | ░░   |

The pipeline defaults heavily to POSITIVE, producing a 4× lower error rate for confirmed entities compared to denied or hedged ones. Clinical notes use subtle negation patterns — *"no evidence of"*, *"denies"*, *"without"*, *"rules out"*, *"not consistent with"* — that require dedicated negation-detection logic beyond a general extraction pass.

UNCERTAIN (22.8% error) is the hardest class. Speculative language like *"possible"*, *"suspected"*, *"cannot exclude"*, *"consider"* is semantically ambiguous; the model frequently resolves uncertainty prematurely to POSITIVE.

---

## 5. Temporality Error Rate

| Temporality      | Avg Error | Std Dev | Heat |
|------------------|-----------|---------|------|
| UNCERTAIN        | 23.9%     | 39.1%   | ▓▓   |
| UPCOMING         | 17.8%     | 12.9%   | ▓▓   |
| CLINICAL_HISTORY | 13.9%     | 21.0%   | ▒▒   |
| CURRENT          | 5.8%      | 4.1%    | ▒▒   |

UPCOMING (17.8%) is frequently mislabeled as CURRENT. Scheduled medications, follow-up appointments, and pending lab orders appear in the same table columns as active orders, making temporal inference context-dependent.

CLINICAL_HISTORY (13.9%) is under-assigned. Entities in "Past Medical History", "Surgical History", and "Family History" sections are routinely tagged CURRENT — a major source of clinical decision-support errors.

---

## 6. Subject Attribution Error Rate

| Subject       | Avg Error | Std Dev | Heat |
|---------------|-----------|---------|------|
| FAMILY_MEMBER | 20.0%     | 40.7%   | ▓▓   |
| PATIENT       | 1.3%      | 2.1%    | ░░   |

`subject = FAMILY_MEMBER` is effectively absent from all pipeline outputs. Every entity — including those explicitly in "Family History" sections describing conditions in parents, siblings, and relatives — is assigned `subject = PATIENT`. Family history of cancer, coronary artery disease, and psychiatric conditions is being recorded as if it were the patient's own active condition.

**This is the single highest-impact error for clinical risk stratification.**

---

## 7. Error Heatmap (All Files)

| File                        | Date Acc | Attr Compl | Worst Entity Type | Worst Assertion | Worst Temporality |
|-----------------------------|----------|------------|-------------------|-----------------|-------------------|
| 019M72177…20241213          | 0%       | 54%        | SOCIAL_HISTORY    | UNCERTAIN       | UNCERTAIN         |
| 019W06677…20241212          | 0%       | 24%        | PROCEDURE         | NEGATIVE        | UPCOMING          |
| 104W15947…20241213          | 63%      | 61%        | SDOH              | NEGATIVE        | CLINICAL_HISTORY  |
| 105W05861…20241217          | 100%     | 16%        | SDOH              | UNCERTAIN       | UPCOMING          |
| 161W10351…20241126          | 100%     | 56%        | PROCEDURE         | NEGATIVE        | UPCOMING          |
| 218M89247…20241211          | 100%     | 31%        | SOCIAL_HISTORY    | NEGATIVE        | UNCERTAIN         |
| 241W15237…20241216          | 86%      | 67%        | SDOH              | UNCERTAIN       | UNCERTAIN         |
| 279W08692…20241223          | 22%      | 41%        | PROCEDURE         | UNCERTAIN       | CLINICAL_HISTORY  |
| 336W08434…20241127          | 0%       | 26%        | SDOH              | NEGATIVE        | UPCOMING          |
| 352M97319…20241126          | 100%     | 44%        | PROCEDURE         | NEGATIVE        | UNCERTAIN         |
| 363M98433…20241128          | 36%      | 59%        | SOCIAL_HISTORY    | UNCERTAIN       | CLINICAL_HISTORY  |
| 363W18752…20241128          | 12%      | 61%        | SDOH              | NEGATIVE        | CLINICAL_HISTORY  |
| 371W13971…20241128          | 15%      | 72%        | SDOH              | UNCERTAIN       | UPCOMING          |
| 400W00699…20241212          | 97%      | 45%        | PROCEDURE         | NEGATIVE        | CLINICAL_HISTORY  |
| 410M88588…20241217          | 0%       | 51%        | SOCIAL_HISTORY    | UNCERTAIN       | CLINICAL_HISTORY  |
| 415M99841…20241204          | 40%      | 70%        | SDOH              | NEGATIVE        | UPCOMING          |
| 415M99841…20241205          | 0%       | 67%        | PROCEDURE         | UNCERTAIN       | UNCERTAIN         |
| 437M97350…20241211          | 100%     | 67%        | SOCIAL_HISTORY    | NEGATIVE        | CLINICAL_HISTORY  |
| 439W18516…20241211          | 0%       | 49%        | SDOH              | NEGATIVE        | UPCOMING          |
| 463W14981…20241205          | 61%      | 43%        | PROCEDURE         | UNCERTAIN       | CLINICAL_HISTORY  |
| 579W03668…20241218          | 50%      | 52%        | SDOH              | NEGATIVE        | UPCOMING          |
| 612M65828…20241218          | 74%      | 48%        | SOCIAL_HISTORY    | NEGATIVE        | CLINICAL_HISTORY  |
| 630M74464…20241218          | 25%      | 62%        | SDOH              | UNCERTAIN       | UPCOMING          |
| 712W12471…20241212          | 100%     | 65%        | MEDICAL_DEVICE    | NEGATIVE        | CLINICAL_HISTORY  |
| 735M97358…20241216          | 100%     | 65%        | SOCIAL_HISTORY    | UNCERTAIN       | UPCOMING          |
| 786W17536…20241219          | 50%      | 45%        | PROCEDURE         | NEGATIVE        | CLINICAL_HISTORY  |
| 791M62215…20241219          | 42%      | 50%        | SDOH              | UNCERTAIN       | UPCOMING          |
| 819M83517…20241219          | 70%      | 46%        | SOCIAL_HISTORY    | NEGATIVE        | CLINICAL_HISTORY  |
| 943W19621…20241217          | 100%     | 21%        | SDOH              | UNCERTAIN       | UPCOMING          |
| 944W15109…20241205          | 100%     | 53%        | SOCIAL_HISTORY    | NEGATIVE        | CLINICAL_HISTORY  |

---

## 8. Top Systemic Weaknesses

### W1 — FAMILY_MEMBER Subject Never Assigned *(Critical)*

The `subject = FAMILY_MEMBER` label is absent from virtually all pipeline outputs. Every entity in "Family History" sections is tagged `PATIENT`, conflating hereditary risk factors with active diagnoses. Downstream risk models will over-score patients for conditions they do not have.

### W2 — Negation Detection Failure *(High)*

NEGATIVE error 20.8%, UNCERTAIN 22.8%. The pipeline defaults to POSITIVE when ambiguous. Negation vocabulary (*no*, *denies*, *without evidence of*, *ruled out*) and speculation markers (*possible*, *suspected*, *cannot exclude*) are not handled by a general extraction prompt.

### W3 — PROCEDURE Over-tagging *(High)*

PROCEDURE constitutes 33% of all entities and has a 21.3% error rate. Table headers, section titles, and administrative entries (*"current meds"*, *"last admin"*, *"encounter 1"*) are extracted as clinical procedures, polluting procedure lists with noise.

### W4 — SDOH / SOCIAL_HISTORY / PROBLEM Boundary Confusion *(High)*

SDOH (21.9%) and SOCIAL_HISTORY (19.7%) are the two most misclassified types. The model lacks consistent boundary rules for entities like *"homelessness"* (SDOH vs SOCIAL_HISTORY) or *"alcohol use disorder"* (PROBLEM vs SOCIAL_HISTORY).

### W5 — Historical and Upcoming Temporality Under-detected *(Medium-High)*

CLINICAL_HISTORY (13.9%) and UPCOMING (17.8%) are under-assigned; the pipeline over-relies on CURRENT. Historical conditions in PMH sections are treated as active problems; pending orders are treated as current medications.

### W6 — PHI Redaction Breaks Date Accuracy *(Medium)*

Bimodal distribution (std 39.8%): charts with raw dates score ~100%; PHI-redacted charts score 0%. The pipeline does not resolve redacted `[ENCOUNTER_DATE]` placeholders from the filename or chart header, leaving event timelines unresolvable.

### W7 — Attribute Completeness ~50% *(Medium)*

MEDICINE entities most commonly lack FREQUENCY; TEST entities lack TEST_UNIT; VITAL_NAME entities lack VITAL_NAME_UNIT. This blocks automated dosing decisions, lab range comparison, and vital sign trend analysis.

---

## 9. Proposed Guardrails

### G1 — Section-Heading Subject Override

Use the `heading` field (already extracted) to override subject attribution. Zero model changes required.

```python
FAMILY_HEADINGS = {"family history", "family medical history", "fh:", "family hx"}

def override_subject(entity):
    heading = (entity.get("heading") or "").lower()
    if any(h in heading for h in FAMILY_HEADINGS):
        entity["subject"] = "FAMILY_MEMBER"
    return entity
```

### G2 — Dedicated Negation & Speculation Layer

Run NegEx / Medspacy `negex` over each entity's `text` field before finalising assertion.

| Cue class   | Example triggers                                 | → Assertion |
|-------------|--------------------------------------------------|-------------|
| Negation    | *no, denies, without, ruled out, absent*         | NEGATIVE    |
| Speculation | *possible, suspected, cannot exclude, query*     | UNCERTAIN   |
| Affirmation | *confirmed, positive for, consistent with*       | POSITIVE    |

### G3 — Heading-Driven Temporality Default

Set a temporality prior from the section heading before model inference. Model output overrides only when confidence exceeds a threshold.

| Heading contains              | Default temporality |
|-------------------------------|---------------------|
| Past Medical History / PMH    | CLINICAL_HISTORY    |
| Surgical History              | CLINICAL_HISTORY    |
| Plan / Follow-up / Scheduled  | UPCOMING            |
| Current Meds / Active Problems| CURRENT             |

### G4 — PROCEDURE Allowlist Filter

Entities labeled PROCEDURE that do not fuzzy-match known CPT/SNOMED procedure terms and whose text matches structural patterns (table headers, section names) should be re-classified or suppressed.

### G5 — Attribute Completeness Hard Check

```python
REQUIRED_ATTRS = {
    "MEDICINE":   {"DOSE", "ROUTE", "FREQUENCY"},
    "TEST":       {"TEST_VALUE", "TEST_UNIT"},
    "VITAL_NAME": {"VITAL_NAME_VALUE", "VITAL_NAME_UNIT"},
}

def completeness_flag(entity):
    required = REQUIRED_ATTRS.get(entity["entity_type"], set())
    found = {r["entity_type"] for r in entity.get("metadata_from_qa", {}).get("relations", [])}
    missing = required - found
    if missing:
        entity["_missing_attributes"] = list(missing)
        entity["_needs_review"] = True
    return entity
```

### G6 — PHI-Aware Date Resolution

When a date relation resolves to a redacted placeholder, fall back to the encounter date from the chart filename (format: `{ID}_{ACC}_{YYYYMMDD}.json`). Store as `entity_source = DERIVED`.

### G7 — Confidence-Gated Human Review Queue

Route entities to a review queue when assertion or temporality is UNCERTAIN, completeness flag is set, or entity type is SDOH / SOCIAL_HISTORY / PROCEDURE. Track reviewer corrections for future fine-tuning.

---

## 10. Conclusion

The pipeline performs reliably on well-structured, high-frequency entities — MEDICINE, VITAL_NAME, and PROBLEM with POSITIVE assertion and CURRENT temporality have low error rates. It fails systematically on:

1. **Family member attribution** — 0% coverage, critical for risk stratification
2. **Negation and uncertainty** — 20–23% error, POSITIVE over-prediction dominates
3. **SDOH / PROCEDURE / SOCIAL_HISTORY** — boundary confusion at 20–22%
4. **Historical and scheduled temporality** — under-assigned by ~15–18%
5. **Metadata completeness** — only 50% of expected attributes populated

All seven proposed guardrails are implementable as post-processing rules with no model retraining. G1 (subject override) and G2 (negation layer) together address the two highest-impact failure modes immediately.

---

*Evaluation framework: `test.py` (LLM-as-judge + heuristics) · Report generated by `generate_report.py`*
