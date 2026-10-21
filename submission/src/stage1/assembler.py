"""
Stage 1 Assembler: orchestrates dedup → profile → conflict → eligibility → brief.
"""
import time
from datetime import datetime, timezone

from src.config import AgentConfig
from src.live_state import LiveState
from src.stage1.brief import ViewerBrief, EligibleGoal
from src.stage1.dedup import deduplicate_and_sort
from src.stage1.profile import resolve_profile
from src.stage1.conflict import resolve_dialect, resolve_subscription_status, to_ist_date
from src.stage1.eligibility import compute_eligible_goals, _days_before, _days_between


def assemble(
    *,
    trigger_event: dict,
    historical_events: list[dict],
    live_events: list[dict],
    today_actions: list[dict],
    config: AgentConfig,
    live_state: LiveState,
) -> ViewerBrief:
    """
    Build a ViewerBrief for one trigger. All inputs are pre-filtered to this user_id.
    """
    assembled_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    user_id = trigger_event["user_id"]
    trigger_event_id = trigger_event["event_id"]
    deliver_at = trigger_event.get("deliver_at") or trigger_event.get("received_at")

    assumptions: list[str] = []

    # Stage 0: holdout check
    arm = config.arms.get(user_id, "agent")
    if arm == "holdout":
        return ViewerBrief(
            user_id=user_id,
            trigger_event_id=trigger_event_id,
            deliver_at=deliver_at,
            assembled_at=assembled_at,
            holdout=True,
            assumptions=["User assigned to holdout arm. No action taken."],
        )

    # Step 1: dedup + sort all events
    raw = historical_events + live_events
    events = deduplicate_and_sort(raw)
    # Filter to only events received at or before deliver_at
    events = [e for e in events if (e.get("received_at") or "") <= deliver_at]

    # Step 2: profile resolution
    profile_rows = config.profiles_raw.get(user_id, [])
    profile = resolve_profile(profile_rows, user_id, trigger_event, assumptions)

    # Step 3: conflict resolution
    dialect, dialect_source, dialect_conflicts = resolve_dialect(
        trigger_event, profile, config.default_dialect, assumptions
    )
    subscription_status, subscription_source = resolve_subscription_status(
        profile, events, deliver_at, assumptions
    )

    # Step 4: eligibility + derived facts
    eligible_goals, derived = compute_eligible_goals(
        user_id=user_id,
        deliver_at=deliver_at,
        events=events,
        profile=profile,
        subscription_status=subscription_status,
        live_state=live_state,
        episodes_by_slug=config.episodes_by_slug,
        assumptions=assumptions,
    )

    # Step 5: G07 resolution — map title_ids to content_slugs, check episode counts
    play_started_by_title_id: dict = derived.get("play_started_by_title_id", {})
    # G07 is not relevant for lapsed-subscription users — G06 is the right goal for them.
    g07_sub_ok = subscription_status not in ("lapsed",)
    if derived.get("_g07_pending") and play_started_by_title_id and g07_sub_ok:
        unfinished = _resolve_unfinished_series(
            play_started_by_title_id=play_started_by_title_id,
            events=events,
            config=config,
            deliver_at=deliver_at,
            assumptions=assumptions,
        )
        derived["unfinished_series"] = unfinished
        if unfinished:
            g = live_state.goals.get("G07")
            if g:
                eligible_goals.append(EligibleGoal(
                    goal_id="G07",
                    name=g["name"],
                    measurable=True,
                    evidence=[
                        f"unfinished_series={unfinished}",
                        "last play 3-21 days ago (verified)",
                    ],
                ))

    # Step 6: available titles in resolved dialect
    available_titles = config.titles_for_dialect(
        dialect=dialect,
        at_utc=deliver_at,
        subscription_status=subscription_status,
        live_catalogue=live_state.catalogue,
    )

    # Step 7: structural constraints
    structural_constraints: dict[str, str] = {}
    if dialect_source == "corpus_default":
        structural_constraints["home_page"] = (
            "disabled: dialect_source=corpus_default; "
            "app only serves home page for its current app_dialect"
        )
    if not available_titles:
        structural_constraints["home_page"] = (
            "disabled: no available titles in resolved dialect"
        )

    # Step 8: frequency cap from today's agent actions (not event stream)
    deliver_ist_date = str(to_ist_date(deliver_at))
    messages_today = 0
    for action in today_actions:
        if action.get("user_id") != user_id:
            continue
        if action.get("type") not in ("push", "whatsapp"):
            continue
        pub_at = action.get("published_at", "")
        if pub_at and str(to_ist_date(pub_at)) == deliver_ist_date:
            messages_today += 1

    # Step 9: platform + signup_at from profile/events
    platform = (profile.get("platform") or trigger_event.get("platform") or "").strip()
    signup_at = derived.get("signup_at", "")

    # Step 10: collect key supporting event IDs for evidence
    key_event_ids: list[str] = []
    for e in reversed(events):  # most recent first
        ev = e.get("event", "")
        eid = e.get("event_id", "")
        if not eid:
            continue
        if ev == "play_started" and len(key_event_ids) < 2:
            key_event_ids.append(eid)
        elif ev in ("purchase_completed", "trial_started", "subscription_started") and eid not in key_event_ids:
            key_event_ids.append(eid)
            break
        if len(key_event_ids) >= 3:
            break

    return ViewerBrief(
        user_id=user_id,
        trigger_event_id=trigger_event_id,
        deliver_at=deliver_at,
        assembled_at=assembled_at,
        holdout=False,
        dialect=dialect,
        dialect_source=dialect_source,
        dialect_conflicts=dialect_conflicts,
        subscription_status=subscription_status,
        subscription_source=subscription_source,
        platform=platform,
        signup_at=signup_at,
        signup_age_days=derived.get("signup_age_days", 9999.0),
        notifications_opt_in=bool(profile.get("notifications_opt_in", False)),
        whatsapp_opt_in=bool(profile.get("whatsapp_opt_in", False)),
        event_types_seen=derived.get("event_types_seen", set()),
        play_days_14d=derived.get("play_days_14d", []),
        unfinished_series=derived.get("unfinished_series", []),
        days_since_last_app_open=derived.get("days_since_last_app_open", 9999.0),
        last_play_received_at=derived.get("last_play_received_at") or None,
        eligible_goals=eligible_goals,
        available_titles=available_titles,
        messages_sent_today_count=messages_today,
        structural_constraints=structural_constraints,
        key_event_ids=key_event_ids,
        assumptions=assumptions,
    )


def _resolve_unfinished_series(
    *,
    play_started_by_title_id: dict,  # title_id -> latest received_at
    events: list[dict],
    config: AgentConfig,
    deliver_at: str,
    assumptions: list[str],
) -> list[str]:
    """
    Returns list of content_slugs where:
    - user has play_started for a title in that slug
    - total episodes > completed episodes for that slug
    - last play_started for that slug was >= 3 days ago
    """
    cutoff_3d = _days_before(deliver_at, 3)
    cutoff_21d = _days_before(deliver_at, 21)

    # Collect completed episode_ids per content_slug from event stream
    completed_by_slug: dict[str, set] = {}
    for e in events:
        if e.get("event") == "episode_completed":
            props = e.get("properties") or {}
            eid = props.get("episode_id", "")
            tid = props.get("title_id", "")
            if tid and tid in config.catalogue_by_id:
                slug = config.catalogue_by_id[tid]["content_slug"]
                completed_by_slug.setdefault(slug, set()).add(eid)

    # Map play_started title_ids to slugs
    slug_last_play: dict[str, str] = {}  # slug -> latest received_at
    for tid, ra in play_started_by_title_id.items():
        if tid in config.catalogue_by_id:
            slug = config.catalogue_by_id[tid]["content_slug"]
            if slug not in slug_last_play or ra > slug_last_play[slug]:
                slug_last_play[slug] = ra

    unfinished: list[str] = []
    for slug, last_play_ra in slug_last_play.items():
        # Must be a show/micro_drama (films don't have episodes to resume)
        # Check via any title with this slug
        sample_title = next(
            (t for t in config.catalogue_by_id.values() if t["content_slug"] == slug),
            None,
        )
        if sample_title and sample_title.get("content_type") == "film":
            continue

        total_episodes = len(config.episodes_by_slug.get(slug, []))
        if total_episodes == 0:
            continue

        completed = len(completed_by_slug.get(slug, set()))
        if completed >= total_episodes:
            continue  # fully watched

        # Last play must be 3-21 days ago:
        # <3d: still actively watching, no nudge needed
        # >21d: fully lapsed, G06 is more appropriate than G07
        if last_play_ra > cutoff_3d or last_play_ra < cutoff_21d:
            continue

        unfinished.append(slug)

    return unfinished
