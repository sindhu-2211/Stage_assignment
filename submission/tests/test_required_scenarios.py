"""
Four required automated test scenarios from the assignment brief.
All use synthetic data — no dependency on the real data pack.
"""
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

# ── helpers ────────────────────────────────────────────────────────────────────

def _make_trigger(event_id="EVT-001", user_id="U-TEST", deliver_at="2026-10-01T10:00:00Z",
                  app_dialect="d1"):
    return {
        "event_id": event_id,
        "user_id": user_id,
        "event": "app_open",
        "received_at": deliver_at,
        "deliver_at": deliver_at,
        "app_dialect": app_dialect,
        "app_language": "hin",
        "platform": "android",
        "properties": {},
    }


def _make_config(default_dialect="d1", arms=None, goals=None):
    cfg = MagicMock()
    cfg.arms = arms or {"U-TEST": "agent"}
    cfg.default_dialect = default_dialect
    cfg.profiles_raw = {}
    cfg.model_faults = {}
    cfg.forbidden_phrases = ["last chance", "hurry"]
    cfg.approved_templates = {
        "wa_recommend_title_v1": {"template_id": "wa_recommend_title_v1", "variables": ["title_name", "dialect_name"]},
    }
    cfg.valid_prices_inr = {"1", "149", "399"}
    cfg.catalogue_by_id = {
        "T0001": {"title_id": "T0001", "content_slug": "slug-a", "title": "Show A",
                  "dialect": "d1", "content_type": "show", "is_premium": False,
                  "available_from": "2026-01-01T00:00:00Z", "available_until": "",
                  "release_date": "2026-09-01", "genres": "Drama"},
        "T0002": {"title_id": "T0002", "content_slug": "slug-b", "title": "Film B",
                  "dialect": "d2", "content_type": "film", "is_premium": False,
                  "available_from": "2026-01-01T00:00:00Z", "available_until": "",
                  "release_date": "2026-09-15", "genres": "Comedy"},
    }
    cfg.catalogue_by_dialect = {
        "d1": [cfg.catalogue_by_id["T0001"]],
        "d2": [cfg.catalogue_by_id["T0002"]],
    }
    cfg.episodes_by_slug = {"slug-a": [
        {"episode_id": "E001", "content_slug": "slug-a", "season": 1, "episode": 1, "minutes": 30.0},
        {"episode_id": "E002", "content_slug": "slug-a", "season": 1, "episode": 2, "minutes": 30.0},
    ]}
    cfg.episode_by_id = {}
    cfg.pricing = {"P_MONTH": {"plan_id": "P_MONTH", "price_inr": 149, "days": 30}}
    if goals is not None:
        cfg.goals = goals
    else:
        cfg.goals = _default_goals()
    cfg.title_available_at = lambda title, at: True
    cfg.titles_for_dialect = lambda dialect, at_utc, subscription_status, live_catalogue=None: (
        [t for t in cfg.catalogue_by_id.values() if t["dialect"] == dialect]
    )
    return cfg


def _default_goals():
    return {
        "G01": {"goal_id": "G01", "name": "first_play_24h", "eligibility": {}, "success": {"event": "play_started", "window_hours": 24}},
        "G02": {"goal_id": "G02", "name": "first_full_episode_3d", "eligibility": {}, "success": {"event": "episode_completed", "window_hours": 72}},
        "G03": {"goal_id": "G03", "name": "second_day_return_2d", "eligibility": {}, "success": {"event": "app_open", "window_hours": 48}},
        "G04": {"goal_id": "G04", "name": "trial_to_paid_7d", "eligibility": {}, "success": {"event": "purchase_completed", "window_hours": 168}},
        "G05": {"goal_id": "G05", "name": "first_paid_7d", "eligibility": {}, "success": {"event": "purchase_completed", "window_hours": 168}},
        "G06": {"goal_id": "G06", "name": "reactivate_lapsed_14d", "eligibility": {}, "success": {"event": "purchase_completed", "window_hours": 336}},
        "G07": {"goal_id": "G07", "name": "resume_series_3d", "eligibility": {}, "success": {"event": "play_started", "window_hours": 72}},
        "G08": {"goal_id": "G08", "name": "try_new_release_7d", "eligibility": {}, "success": {"event": "play_started", "window_hours": 168}},
        "G09": {"goal_id": "G09", "name": "weekly_habit_14d", "eligibility": {}, "success": {"event": "play_started", "window_hours": 336}},
        "G10": {"goal_id": "G10", "name": "meaningful_engagement_7d", "eligibility": {}, "success": {"event": None, "window_hours": 168}},
        "G11": {"goal_id": "G11", "name": "tv_activation_14d", "eligibility": {}, "success": {"event": "tv_app_open", "window_hours": 336}},
        "G12": {"goal_id": "G12", "name": "return_after_absence_7d", "eligibility": {}, "success": {"event": "play_started", "window_hours": 168}},
    }


def _make_live_state(config):
    import copy
    ls = MagicMock()
    ls.catalogue = copy.deepcopy(config.catalogue_by_id)
    ls.goals = copy.deepcopy(config.goals)
    ls.unavailable_deps = set()
    ls.degraded_deps = {}
    ls.model_provider_available.return_value = True
    return ls


# ── Test 1: Duplicate trigger processed only once ───────────────────────────────

def test_idempotent_on_duplicate_trigger(tmp_path):
    """
    Same trigger event_id processed twice → decisions.jsonl has exactly one entry.
    """
    from src.stage1.dedup import deduplicate_and_sort

    event = {"event_id": "E-DUP", "user_id": "U-TEST", "event": "app_open",
             "received_at": "2026-10-01T09:00:00Z", "app_dialect": "d1", "properties": {}}
    duplicate = dict(event)
    duplicate["received_at"] = "2026-10-01T09:05:00Z"  # later delivery, same event_id

    result = deduplicate_and_sort([event, duplicate])

    assert len(result) == 1, "Duplicate event_id must yield exactly one entry"
    assert result[0]["received_at"] == "2026-10-01T09:00:00Z", "Earlier received_at must be kept"


# ── Test 2: Conflicting dialect sources — app_setting wins ──────────────────────

def test_app_setting_beats_profile_and_campaign_dialect():
    """
    trigger.app_dialect='d3', profile.preferred_dialect='d1',
    campaign deeplink contains 'd2'
    → resolved dialect='d3', source='app_setting'
    → all three sources in dialect_conflicts
    """
    from src.stage1.conflict import resolve_dialect

    trigger = {
        "app_dialect": "d3",
        "app_language": "hin",
        "properties": {"deeplink": "ott://c/camp42/d2/title/T0002"},
    }
    profile = {"preferred_dialect": "d1"}
    assumptions = []

    resolved, source, all_sources = resolve_dialect(trigger, profile, "d1", assumptions)

    assert resolved == "d3", f"Expected d3, got {resolved}"
    assert source == "app_setting", f"Expected app_setting, got {source}"
    assert all_sources.get("app_setting") == "d3"
    assert all_sources.get("profile") == "d1"
    assert all_sources.get("campaign_link") == "d2"
    # Conflict assumption must be logged
    assert any("conflict" in a.lower() for a in assumptions), "Conflict assumption not logged"


# ── Test 3: Provider failure → no_action decision, no crash ────────────────────

def test_stage2_provider_failure_produces_no_action_decision():
    """
    MockProvider always raises ProviderTimeoutError
    → DecisionDraft.action_type='no_action', reasoning contains 'provider_timeout'
    → no exception propagates
    """
    from src.stage2.decision import make_decision
    from src.stage1.brief import ViewerBrief, EligibleGoal
    from src.providers.base import ProviderTimeoutError

    class AlwaysTimeoutProvider:
        def decide(self, brief_json, trigger_event_id):
            raise ProviderTimeoutError("injected timeout")

    brief = ViewerBrief(
        user_id="U-FAULT",
        trigger_event_id="EVT-FAULT",
        deliver_at="2026-10-01T10:00:00Z",
        assembled_at="2026-10-01T10:00:00Z",
        dialect="d1",
        dialect_source="app_setting",
        subscription_status="never",
        eligible_goals=[
            EligibleGoal(goal_id="G05", name="first_paid_7d", measurable=True, evidence=["status=never"]),
        ],
    )

    draft = make_decision(brief, AlwaysTimeoutProvider())

    assert draft.action_type == "no_action"
    assert "timeout" in draft.reasoning.lower(), f"Expected timeout in reasoning, got: {draft.reasoning}"


# ── Test 4: goal_rule_corrected applies to subsequent triggers ──────────────────

def test_goal_rule_correction_applies_to_subsequent_triggers():
    """
    G03 success event corrected from 'app_open' to 'play_started' by control event at T.
    LiveState before T: G03.success.event == 'app_open'
    LiveState after T: G03.success.event == 'play_started'
    """
    import copy
    from src.live_state import LiveState

    # Use real goals structure
    goals = {
        "G03": {
            "goal_id": "G03",
            "name": "second_day_return_2d",
            "eligibility": {},
            "success": {
                "event": "app_open",
                "condition": "on a later IST calendar day",
                "window_hours": 48,
            },
        }
    }
    config_mock = MagicMock()
    config_mock.catalogue_by_id = {}
    config_mock.goals = copy.deepcopy(goals)

    ls = LiveState.__new__(LiveState)
    ls.catalogue = {}
    ls.goals = copy.deepcopy(goals)
    ls.unavailable_deps = set()
    ls.degraded_deps = {}

    # Before correction
    assert ls.goals["G03"]["success"]["event"] == "app_open"

    correction_event = {
        "at": "2026-10-01T08:30:00.000Z",
        "type": "goal_rule_corrected",
        "goal_id": "G03",
        "old_success": {"event": "app_open"},
        "new_success": {"event": "play_started", "condition": "on a later IST calendar day"},
    }
    ls.apply(correction_event)

    # After correction
    assert ls.goals["G03"]["success"]["event"] == "play_started", (
        f"Expected play_started, got {ls.goals['G03']['success']['event']}"
    )
    assert ls.goals["G03"]["success"].get("condition") == "on a later IST calendar day"
