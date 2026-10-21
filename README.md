# One User, One Agent — OTT Dialect Platform

An agentic system that assigns one dedicated agent per viewer on a multi-dialect OTT streaming platform. For each viewer trigger, the agent assembles conflict-resolved context, calls an LLM to choose a goal and intervention, independently verifies all constraints, and publishes the action — within a 60-second latency budget.

## Repository structure

```
submission/          ← all source code, tests, and sample output
  src/               ← pipeline stages (Stage 1 / 2 / 3), providers, measurement
  tests/             ← 4 required scenario tests (all passing)
  sample_run/        ← pre-generated decisions, actions, outcomes, reports
  README.md          ← setup and quickstart instructions
  ARCHITECTURE.md    ← design decisions and pipeline detail
  KNOWN_LIMITATIONS.md
  AI_COLLABORATION.md
```

## Quickstart

```bash
cd submission
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# No API key needed — uses pre-recorded LLM responses
MODEL_PROVIDER=replay python3 run_replay.py \
  --pack "../one_user_one_agent_data_pack (4)/one_user_one_agent_pack"

python3 -m pytest tests/ -v
```

See [`submission/README.md`](submission/README.md) for full setup, provider options, and output format.

## Sample run summary

| Metric | Value |
|---|---|
| Total triggers | 2769 |
| Agent-arm decisions | 1397 |
| Holdout-arm (no intervention) | 1372 |
| Actions published | 821 |
| Latency p50 / p95 | 731 ms / 890 ms |
| Latency failures (>60s) | 0 |
| Agent successes | 148 / 1211 decisions with goal |
| Holdout organic paid purchase rate | 2.6% |
| Holdout organic play rate | 62.2% |
