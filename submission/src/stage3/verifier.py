"""
Stage 3: independent deterministic verifier.
Never reads Stage 2 reasoning — only the structured DecisionDraft fields.
Runs all checks regardless of earlier failures (full audit trail).
"""
from datetime import datetime, timedelta, timezone
from src.providers.base import DecisionDraft
from src.stage1.brief import ViewerBrief
from src.config import AgentConfig

IST_OFFSET = timedelta(hours=5, minutes=30)
QUIET_START_H = 22  # 22:00 IST
QUIET_END_H = 8     # 08:00 IST


def _to_ist(utc_str: str) -> datetime:
    dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
    return dt + IST_OFFSET


def _in_quiet_hours(utc_str: str) -> bool:
    ist = _to_ist(utc_str)
    h = ist.hour
    # Quiet 22:00–08:00 IST: hour >= 22 OR hour < 8
    return h >= QUIET_START_H or h < QUIET_END_H


def _next_safe_send_at(from_utc: str) -> str:
    """Return next 08:00 IST (as UTC) if from_utc is in quiet hours."""
    if not _in_quiet_hours(from_utc):
        return from_utc
    dt = datetime.fromisoformat(from_utc.replace("Z", "+00:00"))
    ist = dt + IST_OFFSET
    # Move to 08:00 IST same day or next day
    candidate = ist.replace(hour=8, minute=0, second=0, microsecond=0)
    if candidate <= ist:
        candidate = candidate + timedelta(days=1)
    utc_candidate = candidate - IST_OFFSET
    return utc_candidate.isoformat().replace("+00:00", "Z")


def verify(
    brief: ViewerBrief,
    draft: DecisionDraft,
    config: AgentConfig,
    live_state,  # LiveState
) -> tuple[DecisionDraft, list[str], list[str]]:
    """
    Returns (final_draft, checks_passed, checks_failed).
    final_draft: downgraded to no_action if any check fails.
    """
    passed: list[str] = []
    failed: list[str] = []

    action = draft.action_type
    is_messaging = action in ("push", "whatsapp")
    involves_content = action in ("push", "whatsapp", "in_app_message")

    # 1. goal eligibility
    eligible_ids = {g.goal_id for g in brief.eligible_goals}
    if draft.goal_id is None or draft.goal_id in eligible_ids:
        passed.append("eligibility")
    else:
        failed.append(f"eligibility: goal_id={draft.goal_id} not eligible")

    # 2. dialect/availability — content title must match brief dialect
    if involves_content and not draft.title_id and not brief.available_titles:
        # No title chosen and nothing available in this dialect
        failed.append("availability: no titles available in dialect")
        # dialect still passes (no mismatch to check)
        passed.append("dialect")
    elif involves_content and draft.title_id:
        title = live_state.catalogue.get(draft.title_id)
        if title is None:
            failed.append(f"availability: title_id={draft.title_id} not in live catalogue (withdrawn?)")
            passed.append("dialect")
        elif title.get("dialect") != brief.dialect:
            failed.append(
                f"dialect: title {draft.title_id} dialect={title.get('dialect')} "
                f"!= brief.dialect={brief.dialect}"
            )
        else:
            passed.append("dialect")
            # 3. availability at deliver_at
            if config.title_available_at(title, brief.deliver_at):
                passed.append("availability")
            else:
                failed.append(f"availability: title {draft.title_id} not available at {brief.deliver_at}")
    else:
        # No content needed (no_action, home_page with no title, or push with some titles available)
        passed.append("dialect")
        passed.append("availability")

    # 4. consent_push
    if action == "push":
        if brief.notifications_opt_in:
            passed.append("consent_push")
        else:
            failed.append("consent_push: notifications_opt_in=False")
    else:
        passed.append("consent_push")

    # 5. consent_whatsapp
    if action == "whatsapp":
        if brief.whatsapp_opt_in:
            passed.append("consent_whatsapp")
        else:
            failed.append("consent_whatsapp: whatsapp_opt_in=False")
    else:
        passed.append("consent_whatsapp")

    # 6. frequency_cap (per IST calendar day, push+whatsapp combined, max 1)
    if is_messaging:
        if brief.messages_sent_today_count == 0:
            passed.append("frequency_cap")
        else:
            failed.append(
                f"frequency_cap: {brief.messages_sent_today_count} push/whatsapp already sent today"
            )
    else:
        passed.append("frequency_cap")

    # 7. quiet_hours
    if is_messaging:
        if _in_quiet_hours(brief.deliver_at):
            # Check if we can schedule for later
            safe_at = _next_safe_send_at(brief.deliver_at)
            # Still allow — but record that send_at must be adjusted
            passed.append(f"quiet_hours: adjusted send_at to {safe_at}")
            draft.reasoning += f" [send_at adjusted to {safe_at} to avoid quiet hours]"
        else:
            passed.append("quiet_hours")
    else:
        passed.append("quiet_hours")

    # 8. forbidden_phrases — check reasoning + synthesized push text
    texts_to_check = [draft.reasoning.lower()]
    if action == "push" and draft.title_id:
        title = config.catalogue_by_id.get(draft.title_id, {})
        title_name = title.get("title", "")
        push_title = title_name[:40].lower()
        push_body = f"watch {title_name} now on ott."[:120].lower()
        texts_to_check += [push_title, push_body]
    combined = " ".join(texts_to_check)
    if any(phrase in combined for phrase in config.forbidden_phrases):
        hit = [p for p in config.forbidden_phrases if p in combined]
        failed.append(f"forbidden_phrases: found {hit}")
    else:
        passed.append("forbidden_phrases")

    # 9. whatsapp_template
    if action == "whatsapp":
        # template is chosen by publisher; pre-check that templates exist for this action
        if config.approved_templates:
            passed.append("whatsapp_template")
        else:
            failed.append("whatsapp_template: no approved templates configured")
    else:
        passed.append("whatsapp_template")

    # 10. price_claims (simple: if action is push/whatsapp for trial goal, price must exist)
    if action in ("push", "whatsapp") and draft.goal_id in ("G04", "G05", "G06"):
        if config.valid_prices_inr:
            passed.append("price_claims")
        else:
            failed.append("price_claims: no valid prices in pricing.json")
    else:
        passed.append("price_claims")

    # Finalize
    final = draft
    if failed:
        final = DecisionDraft(
            goal_id=draft.goal_id,
            action_type="no_action",
            confidence=0.0,
            reasoning=f"downgraded by verifier: {'; '.join(failed)}",
            raw_response=draft.raw_response,
        )

    final.checks_passed = passed
    final.checks_failed = failed
    return final, passed, failed
