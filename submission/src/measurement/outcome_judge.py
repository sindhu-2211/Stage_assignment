"""
Outcome judge: determine if each goal succeeded, failed, or is inconclusive.
Reads simulator output events; never reads model reasoning.
"""
import json
from datetime import datetime, timedelta, date
from pathlib import Path
from collections import defaultdict

IST_OFFSET = timedelta(hours=5, minutes=30)


def to_ist_date(utc_str: str) -> date:
    dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
    return (dt + IST_OFFSET).date()


def _parse_utc(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def judge_outcomes(
    decisions_path: Path,
    outcome_events_path: Path,
    goals: dict,
) -> list[dict]:
    """
    Returns list of outcome records:
    {decision_id, viewer_id, goal_id, outcome, evidence_events, window_hours}
    outcome: succeeded | failed | inconclusive | unverifiable | holdout
    """
    decisions = _load_jsonl(decisions_path)
    outcome_events = _load_jsonl(outcome_events_path)

    # Index outcome events by user_id
    events_by_user: dict[str, list[dict]] = defaultdict(list)
    for e in outcome_events:
        uid = e.get("user_id", "")
        if uid:
            events_by_user[uid].append(e)

    results = []
    for dec in decisions:
        if dec.get("holdout"):
            # For holdout: check if purchase_completed or play_started happened organically
            # within 168h — gives a baseline organic conversion rate for comparison
            uid = dec["viewer_id"]
            start_utc = dec.get("deliver_at", "")
            user_events = events_by_user.get(uid, [])
            organic_outcome = "holdout_no_conversion"
            evidence = []
            try:
                start_dt = _parse_utc(start_utc)
                window_end = start_dt + timedelta(hours=168)
                after = [
                    e for e in user_events
                    if start_utc < (e.get("received_at") or "") <= window_end.isoformat().replace("+00:00", "Z")
                ]
                for e in after:
                    if e.get("event") == "purchase_completed":
                        props = e.get("properties") or {}
                        if str(props.get("is_trial", "true")).lower() == "false":
                            organic_outcome = "holdout_organic_purchase"
                            evidence = [e.get("event_id", "")]
                            break
                        organic_outcome = "holdout_organic_trial"
                        evidence = [e.get("event_id", "")]
                if organic_outcome == "holdout_no_conversion":
                    plays = [e for e in after if e.get("event") == "play_started"]
                    if plays:
                        organic_outcome = "holdout_organic_play"
                        evidence = [plays[0].get("event_id", "")]
            except (ValueError, AttributeError):
                pass
            results.append({
                "decision_id": dec["decision_id"],
                "viewer_id": dec["viewer_id"],
                "goal_id": None,
                "outcome": "holdout",
                "holdout_organic": organic_outcome,
                "evidence_events": evidence,
                "window_hours": 168,
            })
            continue

        goal_raw = dec.get("goal")
        goal_id = goal_raw.get("id") if isinstance(goal_raw, dict) else goal_raw
        if not goal_id:
            results.append({
                "decision_id": dec["decision_id"],
                "viewer_id": dec["viewer_id"],
                "goal_id": None,
                "outcome": "no_goal",
                "evidence_events": [],
                "window_hours": None,
            })
            continue

        # G10: always unverifiable
        if goal_id == "G10":
            results.append({
                "decision_id": dec["decision_id"],
                "viewer_id": dec["viewer_id"],
                "goal_id": goal_id,
                "outcome": "unverifiable",
                "evidence_events": [],
                "window_hours": None,
                "note": "success_event=null in goals.json",
            })
            continue

        # G11: should not appear, but guard
        if goal_id == "G11":
            results.append({
                "decision_id": dec["decision_id"],
                "viewer_id": dec["viewer_id"],
                "goal_id": goal_id,
                "outcome": "unverifiable",
                "evidence_events": [],
                "window_hours": None,
                "note": "tv_app_open absent from event schema",
            })
            continue

        goal = goals.get(goal_id)
        if not goal:
            results.append({
                "decision_id": dec["decision_id"],
                "viewer_id": dec["viewer_id"],
                "goal_id": goal_id,
                "outcome": "inconclusive",
                "evidence_events": [],
                "window_hours": None,
                "note": "goal definition not found",
            })
            continue

        success_cfg = goal.get("success", {})
        success_event = success_cfg.get("event")
        window_hours = success_cfg.get("window_hours", 168)

        # Window: from action published_at (or deliver_at if no action)
        action = dec.get("action", {})
        start_utc = dec.get("deliver_at", "")
        try:
            start_dt = _parse_utc(start_utc)
            window_end = start_dt + timedelta(hours=window_hours)
        except (ValueError, AttributeError):
            results.append({
                "decision_id": dec["decision_id"],
                "viewer_id": dec["viewer_id"],
                "goal_id": goal_id,
                "outcome": "inconclusive",
                "evidence_events": [],
                "window_hours": window_hours,
                "note": "could not parse deliver_at",
            })
            continue

        user_events = events_by_user.get(dec["viewer_id"], [])
        # Only events after the decision
        after_decision = [
            e for e in user_events
            if (e.get("received_at") or "") > start_utc
            and (e.get("received_at") or "") <= window_end.isoformat().replace("+00:00", "Z")
        ]

        outcome, evidence = _check_success(
            goal_id=goal_id,
            success_event=success_event,
            success_condition=success_cfg.get("condition", ""),
            after_decision=after_decision,
            start_ist=to_ist_date(start_utc),
            content_slug=_extract_title_id(dec.get("content")),
        )

        results.append({
            "decision_id": dec["decision_id"],
            "viewer_id": dec["viewer_id"],
            "goal_id": goal_id,
            "outcome": outcome,
            "evidence_events": evidence,
            "window_hours": window_hours,
        })

    return results


def _check_success(
    goal_id: str,
    success_event: str,
    success_condition: str,
    after_decision: list[dict],
    start_ist: date,
    content_slug,
) -> tuple[str, list[str]]:
    matching = [e for e in after_decision if e.get("event") == success_event]

    if not matching:
        return "failed", []

    # Goal-specific condition checks
    if goal_id == "G03":
        # success on a LATER IST calendar day than goal start
        for e in matching:
            ra = e.get("received_at", "")
            if ra and to_ist_date(ra) > start_ist:
                return "succeeded", [e.get("event_id", "")]
        return "failed", []

    if goal_id == "G04":
        # purchase_completed with is_trial=false
        for e in matching:
            props = e.get("properties") or {}
            if str(props.get("is_trial", "true")).lower() == "false":
                return "succeeded", [e.get("event_id", "")]
        return "failed", []

    if goal_id == "G05":
        # purchase_completed with is_trial=false
        for e in matching:
            props = e.get("properties") or {}
            if str(props.get("is_trial", "true")).lower() == "false":
                return "succeeded", [e.get("event_id", "")]
        return "failed", []

    if goal_id == "G07":
        # play_started for same content_slug
        if not content_slug:
            return "inconclusive", []
        for e in matching:
            props = e.get("properties") or {}
            if props.get("title_id") == content_slug:
                return "succeeded", [e.get("event_id", "")]
        return "failed", []

    if goal_id == "G08":
        # play_started a title released in last 30 days — simplified: any play counts
        if matching:
            return "succeeded", [matching[0].get("event_id", "")]
        return "failed", []

    if goal_id == "G09":
        # play_started on 3 distinct IST days within window
        play_days = set()
        for e in matching:
            ra = e.get("received_at", "")
            if ra:
                play_days.add(str(to_ist_date(ra)))
        if len(play_days) >= 3:
            return "succeeded", [e.get("event_id", "") for e in matching[:3]]
        return "failed", []

    # Default: any matching event = success
    return "succeeded", [matching[0].get("event_id", "")]


def _extract_title_id(content) -> str | None:
    if isinstance(content, dict):
        return content.get("title_id")
    if isinstance(content, list):
        for item in content:
            if isinstance(item, str) and item.startswith("title:"):
                return item[6:]
    return None


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    result = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                result.append(json.loads(line))
    return result
