#!/usr/bin/env python3
"""Trace one viewer end-to-end: context → goal → action → outcome."""
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

PACK = Path("../one_user_one_agent_data_pack (4)/one_user_one_agent_pack")
SAMPLE = Path("sample_run")

# ── pick a user ──────────────────────────────────────────────────────────────
user_id = sys.argv[1] if len(sys.argv) > 1 else None

decisions = [json.loads(l) for l in open(SAMPLE / "decisions.jsonl")]
actions   = {a["decision_id"]: a for a in (json.loads(l) for l in open(SAMPLE / "actions.jsonl"))}
outcomes  = {o["decision_id"]: o for o in (json.loads(l) for l in open(SAMPLE / "outcomes.jsonl"))}

if user_id:
    matches = [d for d in decisions if d["viewer_id"] == user_id and not d.get("holdout")]
else:
    # pick first agent-arm decision that has an action
    matches = [d for d in decisions if not d.get("holdout") and d["action"]["type"] != "no_action"]

if not matches:
    print(f"No agent-arm decisions found for {user_id or 'any user'}.")
    sys.exit(1)

d = matches[0]
uid = d["viewer_id"]
did = d["decision_id"]

# ── viewer state ─────────────────────────────────────────────────────────────
state_path = SAMPLE / "viewer_state" / f"{uid}.json"
state = json.loads(state_path.read_text()) if state_path.exists() else {}

print("=" * 60)
print(f"VIEWER: {uid}")
print("=" * 60)

# ── viewer profile ────────────────────────────────────────────────────────────
ev = d.get("evidence", [])
print("\n── VIEWER INFO ──────────────────────────────────────────")
for e in ev:
    print(f"  {e}")

conflicts = d.get("dialect", {}).get("conflicts", [])
if conflicts:
    print(f"  dialect conflicts: {conflicts}")

print(f"\n── ASSUMPTIONS ──────────────────────────────────────────")
for a in d.get("assumptions", []):
    print(f"  • {a}")

# ── goal ──────────────────────────────────────────────────────────────────────
goal = d.get("goal")
print(f"\n── GOAL ─────────────────────────────────────────────────")
if goal:
    print(f"  ID       : {goal.get('id')}")
    print(f"  Name     : {goal.get('name')}")
    print(f"  Deadline : {goal.get('deadline')}")
    print(f"  Window   : {goal.get('window_hours')}h")
else:
    print("  No goal selected (no_action decision)")

# ── decision ──────────────────────────────────────────────────────────────────
print(f"\n── DECISION ─────────────────────────────────────────────")
print(f"  ID         : {did}")
print(f"  Action type: {d['action']['type']}")
print(f"  Title ID   : {d['action'].get('title_id') or '—'}")
print(f"  Confidence : {d.get('confidence')}")
print(f"  Status     : {d.get('status')}")
print(f"  Decided in : {d.get('decided_in_ms')}ms")

checks = d.get("checks", {})
if checks.get("failed"):
    print(f"  ✗ Failed checks: {checks['failed']}")
else:
    print(f"  ✓ All checks passed ({len(checks.get('passed', []))} checks)")

# ── action ────────────────────────────────────────────────────────────────────
print(f"\n── ACTION ───────────────────────────────────────────────")
if did in actions:
    a = actions[did]
    print(f"  Action ID : {a['action_id']}")
    print(f"  Type      : {a['type']}")
    if a.get("title_id"):
        print(f"  Title     : {a['title_id']}")
    if a.get("text"):
        print(f"  Text      : {json.dumps(a['text'])}")
    if a.get("send_at"):
        print(f"  Send at   : {a['send_at']}")
    if a.get("deeplink"):
        print(f"  Deeplink  : {a['deeplink']}")
else:
    print("  No action published (no_action or checks failed)")

# ── outcome ───────────────────────────────────────────────────────────────────
print(f"\n── OUTCOME ──────────────────────────────────────────────")
if did in outcomes:
    o = outcomes[did]
    print(f"  Result    : {o['outcome'].upper()}")
    if o.get("evidence_events"):
        print(f"  Evidence  : {o['evidence_events']}")
    if o.get("note"):
        print(f"  Note      : {o['note']}")
else:
    print("  No outcome recorded")

# ── viewer state ──────────────────────────────────────────────────────────────
if state:
    print(f"\n── DURABLE STATE ────────────────────────────────────────")
    print(f"  Current goal     : {state.get('current_goal')}")
    print(f"  Last decision    : {state.get('last_decision_id')}")
    history = state.get("decision_history", [])
    print(f"  Decision history : {len(history)} entries")

print("\n" + "=" * 60)
