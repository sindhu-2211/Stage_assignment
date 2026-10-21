"""Publish verified actions to actions.jsonl."""
import json
from pathlib import Path
from src.providers.base import DecisionDraft
from src.stage1.brief import ViewerBrief
from src.stage3.verifier import _next_safe_send_at, _in_quiet_hours
from src.config import AgentConfig


def publish_action(
    brief: ViewerBrief,
    draft: DecisionDraft,
    config: AgentConfig,
    live_state,
    actions_path: Path,
    action_id: str,
    decision_id: str,
    published_at: str,
) -> dict | None:
    """
    Builds and appends action to actions.jsonl.
    Returns the action dict, or None if no_action.
    """
    if draft.action_type == "no_action":
        return None

    action = {
        "action_id": action_id,
        "decision_id": decision_id,
        "user_id": brief.user_id,
        "trigger_event_id": brief.trigger_event_id,
        "type": draft.action_type,
        "published_at": published_at,
    }

    if draft.action_type == "home_page":
        _build_home_page(action, brief, draft, config, live_state)
    elif draft.action_type == "push":
        _build_push(action, brief, draft, config, published_at)
    elif draft.action_type == "whatsapp":
        _build_whatsapp(action, brief, draft, config, published_at)
    elif draft.action_type == "in_app_message":
        _build_in_app_message(action, brief, draft, config)

    with open(actions_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(action, ensure_ascii=False) + "\n")

    return action


def _build_home_page(action, brief, draft, config, live_state):
    action["dialect"] = brief.dialect
    # Hero: draft.title_id or first available title
    hero = draft.title_id
    if not hero and brief.available_titles:
        hero = brief.available_titles[0]["title_id"]
    action["hero_title_id"] = hero

    # Build rows — use available_titles, at least 3 per row
    titles = brief.available_titles[:30]
    rows = []

    # Row 1: popular_in_dialect (all remaining titles)
    if len(titles) >= 3:
        rows.append({
            "row_type": "popular_in_dialect",
            "title_ids": [t["title_id"] for t in titles[:10]],
        })

    # Row 2: if G07 eligible, next_episode row with unfinished series titles
    if brief.unfinished_series:
        series_titles = [
            t for t in titles
            if t.get("content_slug") in brief.unfinished_series
        ][:10]
        if len(series_titles) >= 3:
            rows.append({"row_type": "next_episode", "title_ids": [t["title_id"] for t in series_titles]})

    # Row 3: new_releases if available
    new_titles = sorted(
        [t for t in titles if t.get("release_date", "") >= _days_before_str(brief.deliver_at, 30)],
        key=lambda t: t.get("release_date", ""),
        reverse=True,
    )[:10]
    if len(new_titles) >= 3:
        rows.append({"row_type": "new_releases", "title_ids": [t["title_id"] for t in new_titles]})

    action["rows"] = rows[:6]  # max 6 rows per interventions.json


def _build_push(action, brief, draft, config, published_at):
    title = None
    title_id = draft.title_id
    if title_id:
        title = config.catalogue_by_id.get(title_id)
    # If LLM returned no title_id, pick first available title in viewer's dialect
    if not title and brief.available_titles:
        picked = brief.available_titles[0]
        title_id = picked["title_id"]
        title = config.catalogue_by_id.get(title_id, picked)

    title_name = title["title"] if title else "a great show"
    action["title_id"] = title_id

    send_at = _next_safe_send_at(published_at)
    action["send_at"] = send_at
    action["text"] = {
        "title": title_name[:40],
        "body": f"Watch {title_name} now on OTT."[:120],
    }
    action["deeplink"] = f"ott://title/{draft.title_id}" if draft.title_id else ""


def _build_whatsapp(action, brief, draft, config, published_at):
    send_at = _next_safe_send_at(published_at)
    action["send_at"] = send_at
    action["title_id"] = draft.title_id

    title = config.catalogue_by_id.get(draft.title_id or "", {})
    title_name = title.get("title", "a great title")

    # Pick template based on goal
    if draft.goal_id in ("G04",):
        # trial ending → wa_trial_ending_v1
        template_id = "wa_trial_ending_v1"
        price = next(iter(config.valid_prices_inr), "149")
        variables = {"plan_price": f"₹{price}"}
    elif draft.goal_id in ("G07",) and _has_new_episode(draft, config):
        template_id = "wa_new_episode_v2"
        ep_num = _latest_episode_number(draft, config)
        variables = {"title_name": title_name, "episode_number": str(ep_num)}
    else:
        template_id = "wa_recommend_title_v1"
        dialect_name = brief.dialect
        variables = {"title_name": title_name, "dialect_name": dialect_name}

    action["template_id"] = template_id
    action["variables"] = variables


def _build_in_app_message(action, brief, draft, config):
    action["title_id"] = draft.title_id
    if draft.title_id:
        title = config.catalogue_by_id.get(draft.title_id, {})
        title_name = title.get("title", "a great title")
        action["text"] = f"Check out {title_name} on OTT!"
        action["deeplink"] = f"ott://title/{draft.title_id}"
    else:
        action["text"] = "We have something new for you. Open the app!"


def _has_new_episode(draft, config) -> bool:
    if not draft.title_id:
        return False
    title = config.catalogue_by_id.get(draft.title_id, {})
    slug = title.get("content_slug", "")
    return bool(config.episodes_by_slug.get(slug))


def _latest_episode_number(draft, config) -> int:
    if not draft.title_id:
        return 1
    title = config.catalogue_by_id.get(draft.title_id, {})
    slug = title.get("content_slug", "")
    episodes = config.episodes_by_slug.get(slug, [])
    if not episodes:
        return 1
    return max(e.get("episode", 1) for e in episodes)


def _days_before_str(utc_str: str, days: int) -> str:
    from datetime import datetime, timedelta
    dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
    return (dt - timedelta(days=days)).strftime("%Y-%m-%d")
