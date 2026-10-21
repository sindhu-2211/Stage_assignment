"""
Goal eligibility checks for G01–G12.
Reads from LiveState.goals (post-control-event patches), never from raw config.goals.
"""
from datetime import datetime, timedelta, date
from src.stage1.brief import EligibleGoal
from src.live_state import LiveState

IST_OFFSET = timedelta(hours=5, minutes=30)


def to_ist_date(utc_str: str) -> date:
    dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
    return (dt + IST_OFFSET).date()


def _days_between(earlier_utc: str, later_utc: str) -> float:
    if not earlier_utc:
        return 9999.0
    try:
        a = datetime.fromisoformat(earlier_utc.replace("Z", "+00:00"))
        b = datetime.fromisoformat(later_utc.replace("Z", "+00:00"))
        return (b - a).total_seconds() / 86400.0
    except (ValueError, AttributeError):
        return 9999.0


def compute_eligible_goals(
    *,
    user_id: str,
    deliver_at: str,
    events: list[dict],  # deduped, sorted by received_at, received_at <= deliver_at
    profile: dict,
    subscription_status: str,
    live_state: LiveState,
    episodes_by_slug: dict,
    assumptions: list[str],
) -> tuple[list[EligibleGoal], dict]:
    """
    Returns (eligible_goals, derived_facts).
    derived_facts: dict with signup_age_days, play_days_14d, unfinished_series,
                   days_since_last_app_open, event_types_seen, last_play_received_at
    """
    deliver_ist = to_ist_date(deliver_at)

    # --- Derived facts from events ---

    signup_at = (profile.get("signup_at") or "").strip()
    # Also check events for signup_completed if profile has no signup_at
    if not signup_at:
        for e in events:
            if e.get("event") == "signup_completed":
                signup_at = e.get("received_at", "")
                break

    signup_age_days = _days_between(signup_at, deliver_at) if signup_at else 9999.0

    event_types_seen: set = set()
    play_started_events: list[dict] = []
    episode_completed_slugs: set = set()
    last_app_open_at: str = ""
    last_play_received_at: str = ""

    for e in events:
        ev = e.get("event", "")
        event_types_seen.add(ev)
        if ev == "play_started":
            play_started_events.append(e)
            ra = e.get("received_at", "")
            if ra > last_play_received_at:
                last_play_received_at = ra
        elif ev == "episode_completed":
            props = e.get("properties") or {}
            tid = props.get("title_id", "")
            # Resolve content_slug from episode_id or title_id — use title_id as proxy
            episode_completed_slugs.add(tid)
        elif ev == "app_open":
            ra = e.get("received_at", "")
            if ra > last_app_open_at:
                last_app_open_at = ra

    # Play days in last 14 days (distinct IST dates)
    cutoff_14d = _days_before(deliver_at, 14)
    play_days_14d_set: set = set()
    for e in play_started_events:
        ra = e.get("received_at", "")
        if ra >= cutoff_14d:
            play_days_14d_set.add(str(to_ist_date(ra)))
    play_days_14d = sorted(play_days_14d_set)

    # Unfinished series for G07
    # A series is unfinished if: user started it (play_started for content_slug),
    # episodes remaining > completed, last play >= 3 days ago
    unfinished_series: list[str] = []
    play_started_by_slug: dict[str, str] = {}  # slug -> latest received_at
    for e in play_started_events:
        props = e.get("properties") or {}
        tid = props.get("title_id", "")
        # We need content_slug; we don't have catalogue here, so return title_ids
        # assembler.py will resolve slugs using config
        ra = e.get("received_at", "")
        if tid not in play_started_by_slug or ra > play_started_by_slug[tid]:
            play_started_by_slug[tid] = ra

    # days_since_last_app_open
    days_since_last_app_open = _days_between(last_app_open_at, deliver_at) if last_app_open_at else 9999.0

    derived_facts = {
        "signup_at": signup_at,
        "signup_age_days": signup_age_days,
        "event_types_seen": event_types_seen,
        "play_days_14d": play_days_14d,
        "unfinished_series": [],  # filled by assembler after slug resolution
        "days_since_last_app_open": days_since_last_app_open,
        "last_app_open_at": last_app_open_at,
        "last_play_received_at": last_play_received_at,
        "play_started_by_title_id": play_started_by_slug,
        "episode_completed_slugs": episode_completed_slugs,
    }

    goals = live_state.goals
    eligible: list[EligibleGoal] = []

    # G01: first_play_24h
    g = goals.get("G01")
    if g:
        if signup_age_days <= 7 and "play_started" not in event_types_seen:
            eligible.append(EligibleGoal(
                goal_id="G01", name=g["name"], measurable=True,
                evidence=[
                    f"signup_age_days={signup_age_days:.1f} (<=7)",
                    "play_started not in event history",
                ],
            ))

    # G02: first_full_episode_3d
    g = goals.get("G02")
    if g:
        if "episode_completed" not in event_types_seen:
            eligible.append(EligibleGoal(
                goal_id="G02", name=g["name"], measurable=True,
                evidence=["episode_completed not in event history"],
            ))

    # G03: second_day_return_2d
    g = goals.get("G03")
    if g:
        if signup_age_days <= 2:
            eligible.append(EligibleGoal(
                goal_id="G03", name=g["name"], measurable=True,
                evidence=[f"signup_age_days={signup_age_days:.1f} (<=2)"],
            ))

    # G04: trial_to_paid_7d
    g = goals.get("G04")
    if g:
        if subscription_status == "trial_active":
            eligible.append(EligibleGoal(
                goal_id="G04", name=g["name"], measurable=True,
                evidence=["subscription_status=trial_active"],
            ))

    # G05: first_paid_7d
    g = goals.get("G05")
    if g:
        if subscription_status == "never":
            eligible.append(EligibleGoal(
                goal_id="G05", name=g["name"], measurable=True,
                evidence=["subscription_status=never"],
            ))

    # G06: reactivate_lapsed_14d
    g = goals.get("G06")
    if g:
        if subscription_status == "lapsed":
            eligible.append(EligibleGoal(
                goal_id="G06", name=g["name"], measurable=True,
                evidence=["subscription_status=lapsed"],
            ))

    # G07: resume_series_3d — slug resolution deferred to assembler
    # We mark it eligible here if there are any play_started title_ids
    # Assembler will filter by actual unfinished series + 3-day gap
    g = goals.get("G07")
    if g:
        derived_facts["_g07_pending"] = True  # assembler resolves this

    # G08: try_new_release_7d
    g = goals.get("G08")
    if g:
        if subscription_status == "active":
            eligible.append(EligibleGoal(
                goal_id="G08", name=g["name"], measurable=True,
                evidence=["subscription_status=active"],
            ))

    # G09: weekly_habit_14d
    g = goals.get("G09")
    if g:
        if subscription_status == "active" and len(play_days_14d) <= 1:
            eligible.append(EligibleGoal(
                goal_id="G09", name=g["name"], measurable=True,
                evidence=[
                    "subscription_status=active",
                    f"play_days_14d={len(play_days_14d)} (<=1)",
                ],
            ))

    # G10: meaningful_engagement_7d — always eligible, never measurable
    g = goals.get("G10")
    if g:
        note = (
            "success_event is null in goals.json. "
            "Outcome cannot be judged from event stream. "
            "Select only if no measurable goal exists."
        )
        eligible.append(EligibleGoal(
            goal_id="G10", name=g["name"], measurable=False,
            evidence=["any user is eligible"],
            assumption=note,
        ))
        assumptions.append(f"G10 included but flagged unmeasurable: {note}")

    # G11: tv_activation_14d — excluded; tv_app_open absent from event schema
    assumptions.append(
        "G11 (tv_activation_14d) excluded: success_event 'tv_app_open' "
        "is not present in the event schema. Cannot measure outcome."
    )

    # G12: return_after_absence_7d
    g = goals.get("G12")
    if g:
        if days_since_last_app_open >= 14:
            eligible.append(EligibleGoal(
                goal_id="G12", name=g["name"], measurable=True,
                evidence=[f"days_since_last_app_open={days_since_last_app_open:.1f} (>=14)"],
            ))

    return eligible, derived_facts


def _days_before(utc_str: str, days: int) -> str:
    """Return ISO UTC string for (utc_str - days)."""
    dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
    return (dt - timedelta(days=days)).isoformat().replace("+00:00", "Z")
