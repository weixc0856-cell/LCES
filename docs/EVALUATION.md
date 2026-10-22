# Model Evaluation, Routing, and Cost

Continuous work from PRD section 9: decide what runs locally, what runs in the
cloud, and prove it with recorded numbers instead of assumptions.

## Fixed benchmark set

`evals/basic.jsonl` is a JSONL set of eight tasks covering the types the PRD
asks for: JSON field extraction, classification, outline, rewrite, concept
explanation, multi-source summary, evidence matching, and complex analysis.

Each line is:

```json
{"id": "classify-001", "task_type": "classification", "system": "...",
 "prompt": "...", "expect": {"kind": "choice", "choices": ["transformer"]},
 "max_tokens": 40, "temperature": 0.2}
```

Check kinds are mechanical:

| kind | Passes when |
|---|---|
| `json_object` | Output parses as a JSON object and contains every listed key |
| `choice` | Output contains one of the listed labels |
| `contains_all` | Output contains every listed term (case-insensitive) |
| `min_chars` | Output has at least the required number of characters |

"Reads nicely" is deliberately not a check. Semantic quality still needs human
review; the benchmark only catches format and coverage failures.

## Running

```powershell
uv run lces eval --provider local
uv run lces eval --provider deepseek
```

Reports go to `var/evals/<timestamp>-<provider>.json` and record provider,
model, LCES/Python/platform versions, per-task pass/fail, failures, latency,
token usage, and a 500-character output excerpt. Running the same set against
local and cloud models produces directly comparable files.

A provider error fails that task and is recorded; it never aborts the run.

## Usage and cost

```powershell
uv run lces usage --pricing config/pricing.yaml
uv run lces usage --project attention-is-all-you-need --pricing config/pricing.yaml
```

All numbers come from `stage_runs` in SQLite: calls, input/output tokens,
failures, wall time between stage start and finish, and estimated cost.

Cost rules:

- A model needs an entry in `config/pricing.yaml`; prices there are
  user-maintained, not authoritative.
- Providers listed under `unmetered_providers` (default: `local`) are reported
  as **未核算**, never as zero. Local inference still costs power and hardware.
- An unpriced model is reported as 未核算 as well.
- The total line lists what was excluded from the priced subtotal.

## Routing and failure escalation

Routing stays opt-in (`--routing config/routing.yaml` or `LCES_ROUTING_FILE`).
Explicit `--provider` still wins over the file. Each stage accepts either a
provider name or an object with a fallback:

```yaml
default: local
stages:
  research: {provider: deepseek, fallback: local}
  outline: local
  generate: {provider: local, fallback: deepseek}
```

When a model stage raises a provider error after its own retries, LCES records
the failed attempt, starts a new stage run with the fallback provider, and
retries once. If the fallback also fails, the task is marked FAILED with the
second error. Both attempts remain visible in `stage_runs`.

Cost saving never overrides quality: the fallback only triggers on a provider
error, and a successful-but-invalid output is still rejected by the schema and
QA gates rather than silently accepted.

## Not implemented

- Automatic routing based on measured quality or budget.
- Per-task cost prediction before running.
- Cloud price verification (the table is a local configuration file).
