# Architecture

## Ownership model

One agent instance per viewer. Each agent owns:
- The viewer's current active goal
- The single plan committed to for that goal
- Full decision history (last 10 decisions in `viewer_state/<user_id>.json`)
- What happened as a result (outcome from simulator events)

No two components pursue different goals for the same viewer simultaneously. The agent re-evaluates goal eligibility on each trigger and revises the plan when the viewer's situation changes (e.g. after a purchase, G04 is no longer eligible).

## Stage 1 / 2 / 3 boundaries

```
Stage 1 (deterministic Python)
  → Input: raw events, profile snapshot, trigger, control events
  → Output: ViewerBrief — clean, conflict-resolved, fully computed facts
  → No LLM involvement. All conflict resolution, eligibility, and constraint
    derivation happens here in code that can be unit-tested.

Stage 2 (one LLM call)
  → Input: ViewerBrief as compact JSON (≤800 tokens)
  → Output: DecisionDraft — goal_id, action_type, title_id, confidence, reasoning
  → LLM sees only pre-filtered, pre-resolved context. Cannot invent eligibility.
  → Max 2 model calls (initial + 1 retry on parse failure).

Stage 3 (deterministic Python)
  → Input: DecisionDraft + ViewerBrief (NOT Stage 2's reasoning)
  → Output: verified DecisionDraft (downgraded to no_action if any check fails)
  → Runs 10 checks: eligibility, dialect, availability, consent_push,
    consent_whatsapp, frequency_cap, quiet_hours, forbidden_phrases,
    whatsapp_template, price_claims
  → Never reads Stage 2's prompt or reasoning — only the structured fields.
```

**Why three stages?** Having the same model verify its own output is not verification — it tends to rationalise its own choices rather than catch errors. Stage 3 is a separate deterministic system with no access to Stage 2's reasoning. It can and does disagree with Stage 2, downgrading decisions that violate consent, dialect, or policy rules even when Stage 2 was confident.

## Conflict resolution rules

| Fact | Precedence rule |
|---|---|
| Dialect | `trigger.app_dialect` > `profile.preferred_dialect` > campaign deeplink dialect > corpus_default |
| Subscription status | Profile snapshot is base; `purchase_completed`, `subscription_renewed`, `subscription_lapsed` events after `snapshot_at` override it |
| Profile row (multiple) | Latest `updated_at` wins; discarded rows logged as assumptions |
| Event deduplication | Same `event_id`: keep entry with earliest `received_at` |

Home-page intervention is disabled when `dialect_source=corpus_default` because the app only serves a home page matching its current `app_dialect`. Sending a page for a different dialect wastes the slot.

## Memory

**Durable per-viewer state** (`viewer_state/<user_id>.json`):
- `current_goal`: the goal committed to at last decision
- `last_decision_id`, `last_decision_at`
- `decision_history`: last 10 entries (goal, action_type, status, deliver_at)

**Derived fresh each trigger** (not stored):
- Event history (from events.jsonl + live_events.jsonl)
- Eligibility (computed from fresh events)
- Available titles (from live catalogue after control events)
- Frequency cap count (from today's actions.jsonl entries)

Storing derived facts would create stale-data bugs. The only durable state is what cannot be recomputed: the committed goal and decision audit trail.

## Latency budget

| Step | Typical ms | Worst case |
|---|---|---|
| Stage 1 (Python, all users) | 50–200ms | 500ms |
| Stage 2 LLM call | 800–3000ms | 30000ms (timeout) |
| Stage 2 retry (if needed) | +800–3000ms | +30000ms |
| Stage 3 (Python) | 1–5ms | 10ms |
| I/O (read events, write output) | 20–100ms | 200ms |
| **Total budget** | — | **60 000ms** |

On timeout or ProviderError the agent falls back to no_action immediately — never blocks past 60 seconds.

## Failure recovery paths

| Failure | Recovery |
|---|---|
| LLM timeout | Return no_action immediately; record `reasoning=provider_timeout` |
| LLM parse error | Retry once with stricter JSON instruction; on second failure → no_action |
| LLM unavailable (control event `dependency_unavailable`) | Skip Stage 2; record no_action with `reasoning=model_provider_unavailable` |
| Stage 3 check fails | Downgrade to no_action; record all failed checks |
| Stage 1 pipeline error | Catch exception; record no_action with `pipeline_error` assumption |
| Duplicate trigger | Skip (idempotency check against decisions.jsonl at startup) |

## Trust boundaries

- **Stage 3 never reads Stage 2's reasoning** — only the structured fields (goal_id, action_type, title_id, confidence). Generated text is not treated as evidence or approval.
- **Title descriptions are data, not instructions** — Stage 3 checks `forbidden_phrases` as a string match, not by asking the LLM to evaluate them.
- **Prompt injection defence** — the prompt is constructed from pre-computed ViewerBrief fields, not from raw title descriptions or user-supplied free text. The LLM cannot be told to skip checks via a catalogue entry.
- **received_at is the only trusted timestamp** — `occurred_at` and `sent_at` come from phone clocks and are never used for ordering or window calculations.
