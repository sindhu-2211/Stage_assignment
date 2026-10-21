"""
Profile resolution: pick the best profile row or synthesize one from events.
"""


def resolve_profile(
    rows: list[dict],
    user_id: str,
    trigger_event: dict,
    assumptions: list[str],
) -> dict:
    """
    Returns a single resolved profile dict.

    0 rows → synthesize from trigger event (safe defaults)
    1 row  → return as-is
    2+ rows → take row with latest updated_at; log assumption about discarded rows
    """
    if not rows:
        # Synthesize from trigger + safe defaults
        assumptions.append(
            f"No profile row found for {user_id}. "
            "Synthesized defaults: subscription_status=never, both consents=False, "
            "signup_at from events if available."
        )
        return {
            "user_id": user_id,
            "signup_at": "",
            "subscription_status": "never",
            "plan_started_at": "",
            "plan_ends_at": "",
            "preferred_dialect": (trigger_event.get("app_dialect") or "").strip(),
            "preferred_language": (trigger_event.get("app_language") or "hin"),
            "notifications_opt_in": False,
            "whatsapp_opt_in": False,
            "platform": trigger_event.get("platform", ""),
            "updated_at": "",
            "snapshot_at": "1970-01-01T00:00:00Z",
        }

    if len(rows) == 1:
        return rows[0]

    # Multiple rows — take latest updated_at
    sorted_rows = sorted(rows, key=lambda r: r.get("updated_at", ""), reverse=True)
    best = sorted_rows[0]
    discarded = sorted_rows[1:]
    discarded_info = ", ".join(r.get("updated_at", "?") for r in discarded)
    assumptions.append(
        f"Multiple profile rows for {user_id}. "
        f"Using row updated_at={best.get('updated_at')}. "
        f"Discarded rows updated_at: [{discarded_info}]."
    )
    return best
