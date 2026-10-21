"""
Rule-based provider: deterministic decisions without any API call.
Used to generate sample_run/llm_cache.jsonl for evaluator replay.
"""
import json
from src.providers.base import ModelProvider, DecisionDraft

# Goal priority: measurable goals first, ordered by specificity
_GOAL_PRIORITY = ["G01", "G02", "G03", "G04", "G05", "G06", "G07",
                  "G08", "G09", "G12", "G10", "G11"]

# Action type priority (best engagement first)
_ACTION_PRIORITY = ["push", "whatsapp", "in_app_message", "home_page"]


class RuleBasedProvider(ModelProvider):
    """Deterministic rule-based decisions. No API key needed."""

    def decide(self, viewer_brief_json: dict, trigger_event_id: str) -> DecisionDraft:
        goals = viewer_brief_json.get("eligible_goals", [])
        titles = viewer_brief_json.get("available_titles", [])
        constraints = viewer_brief_json.get("structural_constraints", {})
        notif_opt = viewer_brief_json.get("notifications_opt_in", False)
        wa_opt = viewer_brief_json.get("whatsapp_opt_in", False)
        titles_count = viewer_brief_json.get("available_titles_count", 0)

        if not goals:
            return self._no_action("no eligible goals", trigger_event_id)

        # Pick best measurable goal
        chosen_goal = None
        for gid in _GOAL_PRIORITY:
            for g in goals:
                if g["goal_id"] == gid and g.get("measurable", True):
                    chosen_goal = g
                    break
            if chosen_goal:
                break
        # Fall back to any goal (including unmeasurable)
        if not chosen_goal:
            chosen_goal = goals[0]

        # Pick best available action
        available = []
        if notif_opt:
            available.append("push")
        if wa_opt:
            available.append("whatsapp")
        if titles_count > 0:
            available.append("in_app_message")
        if titles_count > 0 and "home_page" not in constraints:
            available.append("home_page")

        if not available:
            return self._no_action("no available action types", trigger_event_id)

        # Pick highest priority available action
        chosen_action = None
        for a in _ACTION_PRIORITY:
            if a in available:
                chosen_action = a
                break
        if not chosen_action:
            chosen_action = available[0]

        # Pick title for content actions
        title_id = None
        if chosen_action in ("push", "whatsapp", "in_app_message") and titles:
            title_id = titles[0]["title_id"]

        confidence = 0.75 if chosen_goal.get("measurable", True) else 0.45

        raw = json.dumps({
            "goal_id": chosen_goal["goal_id"],
            "action_type": chosen_action,
            "title_id": title_id,
            "confidence": confidence,
            "reasoning": f"rule-based: goal={chosen_goal['goal_id']} action={chosen_action}",
        })

        return DecisionDraft(
            goal_id=chosen_goal["goal_id"],
            action_type=chosen_action,
            title_id=title_id,
            confidence=confidence,
            reasoning=f"rule-based: goal={chosen_goal['goal_id']} action={chosen_action}",
            raw_response=raw,
        )

    def _no_action(self, reason: str, trigger_event_id: str) -> DecisionDraft:
        raw = json.dumps({"goal_id": None, "action_type": "no_action",
                          "title_id": None, "confidence": 0.0, "reasoning": reason})
        return DecisionDraft(action_type="no_action", reasoning=reason, raw_response=raw)
