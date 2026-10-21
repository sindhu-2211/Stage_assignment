# One User, One Agent — OTT Dialect Platform

A production-style agentic system that assigns one dedicated agent per viewer on a multi-dialect OTT streaming platform. For each viewer trigger, the agent decides the right goal, picks the right intervention in the right dialect, verifies every constraint, and publishes the action — all within a 60-second latency budget.

---

## What this system does

When a viewer opens the app, a trigger fires. The agent:

1. **Assembles context** (Stage 1, deterministic Python) — resolves dialect conflicts, computes subscription status from live events, checks eligibility for all 12 goals, and builds a conflict-resolved `ViewerBrief`.
2. **Makes a decision** (Stage 2, one LLM call) — the LLM sees only pre-resolved context (≤800 tokens) and outputs: `goal_id`, `action_type`, `title_id`, `confidence`, `reasoning`.
3. **Verifies the decision** (Stage 3, deterministic Python) — runs 10 independent checks (consent, dialect match, availability, frequency cap, quiet hours, forbidden phrases, price claims). Downgrades to `no_action` if any check fails. Stage 3 never reads Stage 2's reasoning — only its structured output fields.
4. **Publishes the action** — push notification, in-app message, or home page personalization, with the correct dialect content.

Each viewer gets their own agent instance. No viewer shares state with another.

---

## Assignment context

- **Platform**: Multi-dialect OTT streaming service (dialects d1–d6, languages Hindi/Tamil/Telugu/Kannada/Malayalam/Marathi)
- **Goals**: 12 business goals (G01–G12): new-user activation, trial conversion, paid conversion, lapsed reactivation, series resumption, habit building, new release trials
- **Evaluation**: Agent-arm vs randomised holdout arm. 2769 triggers, 50/50 split.
- **Budget**: ≤60s per decision, ≤8 model calls, ≤20 tool calls

---

## Quickstart — zero API key needed

The `sample_run/` directory contains pre-recorded LLM responses. Run without any API key:

```bash
cd submission
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

MODEL_PROVIDER=replay python3 run_replay.py \
  --pack "../one_user_one_agent_data_pack (4)/one_user_one_agent_pack"
```

This replays all 2769 triggers using cached responses, regenerates decisions and actions, and takes ~30 seconds.

---

## Run with a live LLM

| Provider | Command |
|---|---|
| Gemini (free tier) | `GOOGLE_API_KEY=your-key python3 run_replay.py --pack <pack>` |
| AWS Bedrock (Llama3) | `MODEL_PROVIDER=bedrock AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... python3 run_replay.py --pack <pack>` |
| Anthropic | `MODEL_PROVIDER=anthropic ANTHROPIC_API_KEY=your-key python3 run_replay.py --pack <pack>` |
| Ollama (local) | `MODEL_PROVIDER=ollama OLLAMA_MODEL=llama3.1 python3 run_replay.py --pack <pack>` |
| Rule-based (no LLM) | `MODEL_PROVIDER=rulebased python3 run_replay.py --pack <pack>` |

Free Gemini key: https://aistudio.google.com/apikey

---

## Run tests

```bash
python3 -m pytest tests/ -v
```

4 tests covering: stale trigger handling, dialect conflict resolution, consent blocking, catalogue injection defence.

---

## Regenerate reports after replay

```bash
python3 generate_reports.py \
  --pack "../one_user_one_agent_data_pack (4)/one_user_one_agent_pack"
```

Regenerates `outcomes.jsonl`, `impact_report.md`, `latency_report.json`, `final_report.md`.

---

## Trace a single viewer end-to-end

```bash
python3 trace_viewer.py U-02344
```

Prints the full decision pipeline for one viewer: raw events → profile → eligible goals → LLM draft → verifier checks → published action → outcome.

---

## Sample run results

Pre-generated in `sample_run/`. Key numbers:

| Metric | Value |
|---|---|
| Total triggers | 2769 |
| Agent-arm decisions | 1397 |
| Holdout-arm (no intervention) | 1372 |
| Actions published | 821 |
| Push notifications | 588 |
| In-app messages | 231 |
| Latency p50 | 731 ms |
| Latency p95 | 890 ms |
| Latency failures (>60s) | 0 |
| Agent successes (goal met) | 148 / 1211 decisions with goal |

**Most common goals**: G07 resume series (597), G02 first episode (184), G09 weekly habit (113), G06 lapsed reactivation (111)

**Holdout organic baseline** (no intervention, same 7-day window): 2.6% paid purchase, 62.2% any play.

---

## Output files

```
sample_run/
├── decisions.jsonl        # One record per trigger. Fields:
│                          #   decision_id, viewer_id, trigger, goal,
│                          #   action, dialect, content, confidence,
│                          #   confidence_reason, evidence[], assumptions[],
│                          #   checks.passed[], checks.failed[],
│                          #   decided_in_ms, status, holdout
├── actions.jsonl          # Published interventions (push/in_app/home_page)
├── outcomes.jsonl         # Per-decision outcome: succeeded/failed/holdout/...
├── llm_cache.jsonl        # Pre-recorded LLM responses (for replay mode)
├── viewer_state/          # Per-viewer durable state (current goal, history)
├── impact_report.md       # Agent success rates + holdout organic baseline
├── final_report.md        # Summary table
├── latency_report.json    # p50/p95/p99/max latency
└── sim/
    ├── outcome_events.jsonl
    └── simulator_report.json
```

### Decision record format

```json
{
  "decision_id": "D-00001",
  "viewer_id": "U-02344",
  "trigger": {"event_id": "...", "event": "app_open", "received_at": "..."},
  "goal": {"id": "G07", "name": "resume_series_3d", "deadline": "..."},
  "action": {"type": "push", "action_id": "A-00001", "title_id": "T0910"},
  "dialect": {"used": "d3", "source": "app_setting", "conflicts": ["profile:d1"]},
  "confidence": 0.85,
  "confidence_reason": "Viewer has unfinished series unwatched for 12 days",
  "evidence": [
    "event:9ffd7200-...",
    "profile:dialect_d3_src_app_setting",
    "conflict:profile:d1",
    "catalogue:T0910",
    "goal_rule:G07"
  ],
  "checks": {
    "passed": ["eligibility", "dialect", "availability", "consent_push", "frequency_cap", "quiet_hours", ...],
    "failed": []
  },
  "decided_in_ms": 731.4,
  "status": "ok",
  "holdout": false
}
```

`status` values: `ok` | `holdout` | `downgraded` | `no_action` | `latency_failure`

---

## Architecture overview

```
Trigger event
     │
     ▼
Stage 1: Assembler (deterministic Python)
  • Dedup + sort events
  • Resolve dialect conflict (app_setting > profile > campaign_link > corpus_default)
  • Resolve subscription status (profile snapshot + override from live events)
  • Compute eligible goals from event history
  • Check frequency cap from today's agent actions
  • Build ViewerBrief (compact, conflict-resolved)
     │
     ▼
Stage 2: LLM Decision (one model call, ≤800 token prompt)
  • Input: ViewerBrief as JSON
  • Output: goal_id, action_type, title_id, confidence, reasoning
     │
     ▼
Stage 3: Verifier (deterministic Python, independent of Stage 2 reasoning)
  • 10 checks: eligibility, dialect, availability, consent_push,
    consent_whatsapp, frequency_cap, quiet_hours, forbidden_phrases,
    whatsapp_template, price_claims
  • Fails → downgrade to no_action (full check list still recorded)
     │
     ▼
Publisher → actions.jsonl
Recorder  → decisions.jsonl + viewer_state/
```

Full details: `ARCHITECTURE.md`

---

## Surprise event handling

| Event | Handling |
|---|---|
| Stale offline trigger (>48h age) | Stage 1 detects, returns `no_action` with `stale_trigger` reason |
| Model unavailable | `control_events.jsonl` `model_provider_down` event disables Stage 2; returns `no_action` |
| Catalogue injection attempt | `_sanitize_catalogue_text()` strips prompt-injection patterns before they reach Stage 2 prompt |
| Late purchase event | Subscription status override from live events (processed before eligibility check) |
| Dialect conflict | Resolved by priority rule; both sources logged in `evidence[]` and `assumptions[]` |
| Corrected goal rule | `control_events.jsonl` `goal_updated` event updates live state; applies to all subsequent triggers |
| Traffic spike | Synchronous pipeline; each decision independent. No shared mutable state between viewers. |

---

## Measurement

Impact is measured against the randomised holdout arm (arms.csv assigns users before the replay day). The holdout arm receives no intervention. Both arms have the same prior distribution by randomisation.

Why naive "served vs all users" comparison misleads:
- **Selection bias**: the agent only acts on users who triggered. Holdout users also triggered but received no intervention — that is the correct baseline.
- **Eligibility confound**: comparing a G01-eligible user (new, no plays) to the average user mixes eligibility tiers.

See `sample_run/impact_report.md` for full per-goal breakdown.

---

## Other docs

| File | Contents |
|---|---|
| `ARCHITECTURE.md` | Stage boundaries, conflict resolution rules, memory model, latency budget |
| `KNOWN_LIMITATIONS.md` | G10/G11 measurement gaps, dialect=NA, profile snapshot staleness, frequency cap scope |
| `AI_COLLABORATION.md` | How AI tools were used during development |
