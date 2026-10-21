"""
Conflict resolution for dialect and subscription status.

Dialect precedence (per assignment + interventions.json dialect_rule):
    app_setting > profile > campaign_link > corpus_default

Subscription precedence:
    Profile snapshot is base; purchase/renewal/lapse events after snapshot_at override it.
"""
from datetime import timedelta
from datetime import datetime


IST_OFFSET = timedelta(hours=5, minutes=30)


def to_ist_date(utc_str: str):
    dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
    return (dt + IST_OFFSET).date()


def resolve_dialect(
    trigger_event: dict,
    profile: dict,
    default_dialect: str,
    assumptions: list[str],
) -> tuple[str, str, dict]:
    """
    Returns (resolved_dialect, source, all_sources_dict).
    source one of: app_setting | profile | campaign_link | corpus_default
    """
    all_sources: dict[str, str] = {}

    # Source 1: trigger.app_dialect (app settings feed — most authoritative)
    app_d = (trigger_event.get("app_dialect") or "").strip() or None
    if app_d:
        all_sources["app_setting"] = app_d

    # Source 2: profile.preferred_dialect
    prof_d = None
    if profile:
        prof_d = (profile.get("preferred_dialect") or "").strip() or None
    if prof_d:
        all_sources["profile"] = prof_d

    # Source 3: campaign deeplink dialect  ott://c/<campaign>/<dialect>/title/<id>
    camp_d = None
    props = trigger_event.get("properties") or {}
    deeplink = (props.get("deeplink") or "").strip()
    if deeplink and "/c/" in deeplink:
        parts = deeplink.split("/")
        try:
            c_idx = parts.index("c")
            # format: ott://c/<campaign>/<dialect>/title/<id>
            # parts after split on "/" for "ott://c/camp/d2/title/T001":
            # ['ott:', '', 'c', 'camp', 'd2', 'title', 'T001']
            camp_d = parts[c_idx + 2] if len(parts) > c_idx + 2 else None
            if camp_d:
                camp_d = camp_d.strip() or None
        except (ValueError, IndexError):
            camp_d = None
    if camp_d:
        all_sources["campaign_link"] = camp_d

    # Apply precedence
    if app_d:
        resolved, source = app_d, "app_setting"
    elif prof_d:
        resolved, source = prof_d, "profile"
    elif camp_d:
        resolved, source = camp_d, "campaign_link"
    else:
        resolved, source = default_dialect, "corpus_default"
        assumptions.append(
            "Dialect resolved to corpus_default (no app_setting, profile, or campaign_link). "
            "home_page intervention disabled: app only serves home page for its current dialect."
        )

    # Log conflict if multiple sources disagree
    distinct = set(all_sources.values())
    if len(distinct) > 1:
        assumptions.append(
            f"Dialect conflict detected. Sources: {all_sources}. "
            f"Resolved={resolved} via {source} (app_setting > profile > campaign_link > corpus_default)."
        )

    return resolved, source, all_sources


def resolve_subscription_status(
    profile: dict,
    events: list[dict],
    deliver_at: str,
    assumptions: list[str],
) -> tuple[str, str]:
    """
    Returns (status, source).
    Applies purchase/renewal/lapse events that arrived after snapshot_at and before deliver_at.
    """
    snapshot_at = (profile.get("snapshot_at") or "1970-01-01T00:00:00Z").strip()
    status = (profile.get("subscription_status") or "never").strip()
    source = "profile_snapshot"

    override_events = [
        e for e in events
        if e.get("event") in ("purchase_completed", "subscription_renewed", "subscription_lapsed")
        and (e.get("received_at") or "") > snapshot_at
        and (e.get("received_at") or "") <= deliver_at
    ]
    override_events.sort(key=lambda e: e.get("received_at", ""))

    for e in override_events:
        ev = e["event"]
        if ev == "purchase_completed":
            props = e.get("properties") or {}
            is_trial = str(props.get("is_trial", "false")).lower() == "true"
            status = "trial_active" if is_trial else "active"
            source = "event_stream"
        elif ev == "subscription_renewed":
            status = "active"
            source = "event_stream"
        elif ev == "subscription_lapsed":
            status = "lapsed"
            source = "event_stream"

    if source == "event_stream":
        assumptions.append(
            f"Subscription status overridden by event stream to '{status}' "
            f"({len(override_events)} events after snapshot_at={snapshot_at})."
        )

    return status, source
