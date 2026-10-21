"""Write decisions to decisions.jsonl and update per-viewer state."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from src.providers.base import DecisionDraft
from src.stage1.brief import ViewerBrief


def record_decision(
    brief: ViewerBrief,
    draft: DecisionDraft,
    decision_id: str,
    action_id: str | None,
    decided_in_ms: float,
    actions_path: Path,
    decisions_path: Path,
    state_dir: Path,
    goals: dict | None = None,
    trigger_event: dict | None = None,
) -> dict:
    """
    Write one decision entry to decisions.jsonl.
    Returns the decision dict.
    """
    status = "ok"
    if decided_in_ms > 60_000:
        status = "latency_failure"
    elif brief.holdout:
        status = "holdout"
    elif draft.checks_failed:
        status = "downgraded"
    elif draft.action_type == "no_action":
        status = "no_action"

    decision = {
        "decision_id": decision_id,
        "viewer_id": brief.user_id,
        "trigger": _build_trigger(brief, trigger_event),
        "goal": _build_goal(draft.goal_id, brief.deliver_at, goals),
        "action": {
            "type": draft.action_type,
            "action_id": action_id,
            "title_id": draft.title_id,
        },
        "dialect": _build_dialect(brief),
        "content": _build_content(draft),
        "confidence": draft.confidence,
        "confidence_reason": _extract_confidence_reason(draft),
        "evidence": _build_evidence(brief, draft),
        "assumptions": brief.assumptions,
        "checks": {
            "passed": draft.checks_passed,
            "failed": draft.checks_failed,
        },
        "decided_in_ms": round(decided_in_ms, 1),
        "status": status,
        "holdout": brief.holdout,
        "assembled_at": brief.assembled_at,
        "deliver_at": brief.deliver_at,
    }

    if status == "no_action" and draft.reasoning:
        decision["no_action_reason"] = draft.reasoning[:200]

    with open(decisions_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(decision, ensure_ascii=False) + "\n")

    if not brief.holdout:
        _update_viewer_state(brief, decision, state_dir)

    return decision


def _build_trigger(brief: ViewerBrief, trigger_event: dict | None) -> dict:
    if trigger_event:
        received = trigger_event.get("received_at", brief.deliver_at)
        try:
            d1 = datetime.fromisoformat(brief.deliver_at.replace("Z", "+00:00"))
            d2 = datetime.fromisoformat(received.replace("Z", "+00:00"))
            age_s = round(abs((d1 - d2).total_seconds()))
        except (ValueError, AttributeError):
            age_s = 0
        return {
            "event_id": brief.trigger_event_id,
            "event": trigger_event.get("event", "app_open"),
            "received_at": received,
            "event_age_s": age_s,
        }
    return {"event_id": brief.trigger_event_id}


def _build_goal(goal_id: str | None, deliver_at: str, goals: dict | None) -> dict | None:
    if not goal_id:
        return None
    result: dict = {"id": goal_id}
    if goals:
        goal = goals.get(goal_id, {})
        window_hours = goal.get("success", {}).get("window_hours", 168)
        result["name"] = goal.get("name", "")
        try:
            dt = datetime.fromisoformat(deliver_at.replace("Z", "+00:00"))
            deadline = (dt + timedelta(hours=window_hours)).isoformat().replace("+00:00", "Z")
            result["deadline"] = deadline
            result["window_hours"] = window_hours
        except (ValueError, AttributeError):
            pass
    return result


def _build_dialect(brief: ViewerBrief) -> dict:
    conflicts = [
        f"{src}:{val}"
        for src, val in (brief.dialect_conflicts or {}).items()
        if src != brief.dialect_source
    ]
    return {
        "used": brief.dialect,
        "source": brief.dialect_source,
        "conflicts": conflicts,
    }


def _build_content(draft: DecisionDraft) -> list[str]:
    if draft.title_id:
        return [f"title:{draft.title_id}"]
    return []


def _extract_confidence_reason(draft: DecisionDraft) -> str:
    text = (draft.reasoning or "").strip()
    if not text:
        return ""
    # Try first sentence (period-delimited)
    first = text.split(".")[0].strip()
    if first and len(first) <= 120:
        return first
    # Fall back to word-boundary truncation to avoid mid-word cut
    truncated = text[:117].rsplit(" ", 1)[0]
    return (truncated + "...") if truncated else ""


def _build_evidence(brief: ViewerBrief, draft: DecisionDraft | None = None) -> list[str]:
    """
    Machine-parseable evidence references in format type:id.
    Format: event:{event_id}, catalogue:{title_id}, goal_rule:{goal_id},
            profile:{fact}, conflict:{description}
    """
    ev = []
    # Trigger event that fired this decision
    ev.append(f"event:{brief.trigger_event_id}")
    # Key supporting events (play, purchase, etc.)
    for eid in (brief.key_event_ids or [])[:3]:
        ev.append(f"event:{eid}")
    # Profile facts with source
    ev.append(f"profile:subscription_{brief.subscription_status}_src_{brief.subscription_source}")
    ev.append(f"profile:dialect_{brief.dialect}_src_{brief.dialect_source}")
    # Dialect conflict if present
    if brief.dialect_conflicts:
        for src, val in (brief.dialect_conflicts or {}).items():
            if src != brief.dialect_source:
                ev.append(f"conflict:dialect_{src}={val}")
    # Recommended catalogue item
    if draft and draft.title_id:
        ev.append(f"catalogue:{draft.title_id}")
    # Goal rule applied
    if draft and draft.goal_id:
        ev.append(f"goal_rule:{draft.goal_id}")
    return ev


def _update_viewer_state(brief: ViewerBrief, decision: dict, state_dir: Path) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / f"{brief.user_id}.json"
    state = {}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text())
        except (json.JSONDecodeError, OSError):
            state = {}

    state["user_id"] = brief.user_id
    state["current_goal"] = decision["goal"]
    state["last_decision_id"] = decision["decision_id"]
    state["last_decision_at"] = decision["deliver_at"]

    history = state.get("decision_history", [])
    existing_ids = {e.get("decision_id") for e in history}
    if decision["decision_id"] not in existing_ids:
        history.append({
            "decision_id": decision["decision_id"],
            "goal": decision["goal"],
            "action_type": decision["action"]["type"],
            "deliver_at": decision["deliver_at"],
            "status": decision["status"],
        })
    state["decision_history"] = history[-10:]  # keep last 10

    state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False))
