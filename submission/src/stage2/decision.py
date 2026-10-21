"""Stage 2: call LLM, parse + validate response, handle failures gracefully."""
from src.providers.base import ModelProvider, DecisionDraft, ProviderError, ProviderTimeoutError
from src.stage1.brief import ViewerBrief

ALLOWED_ACTION_TYPES = {"home_page", "push", "whatsapp", "in_app_message", "no_action"}


def make_decision(
    brief: ViewerBrief,
    provider: ModelProvider,
) -> DecisionDraft:
    """
    Calls provider, validates response. On failure returns no_action draft.
    Max 2 model calls (initial + 1 retry on parse/validation failure).
    """
    brief_json = brief.to_dict()
    eligible_goal_ids = {g.goal_id for g in brief.eligible_goals}

    for attempt in range(2):
        try:
            draft = provider.decide(brief_json, brief.trigger_event_id)
        except ProviderTimeoutError as e:
            return _no_action(f"provider_timeout: {e}")
        except ProviderError as e:
            if attempt == 0:
                continue  # retry once
            return _no_action(f"provider_error: {e}")

        # Validate
        errors = _validate(draft, eligible_goal_ids, brief)
        if not errors:
            return draft

        if attempt == 0:
            # One retry; could pass stricter hint but provider interface is simple
            continue
        # Second failure — fallback
        return _no_action(f"validation_failed: {'; '.join(errors)}")

    return _no_action("max_attempts_reached")


def _validate(draft: DecisionDraft, eligible_goal_ids: set, brief: ViewerBrief) -> list[str]:
    errors = []

    if draft.action_type not in ALLOWED_ACTION_TYPES:
        errors.append(f"invalid action_type={draft.action_type!r}")

    if draft.goal_id and draft.goal_id not in eligible_goal_ids:
        errors.append(f"goal_id={draft.goal_id} not in eligible_goals")

    if not (0.0 <= draft.confidence <= 1.0):
        errors.append(f"confidence={draft.confidence} out of [0,1]")

    # Structural constraint check
    constraints = brief.structural_constraints
    if draft.action_type == "home_page" and "home_page" in constraints:
        errors.append(f"home_page structurally disabled: {constraints['home_page']}")

    return errors


def _no_action(reason: str) -> DecisionDraft:
    return DecisionDraft(
        goal_id=None,
        action_type="no_action",
        confidence=0.0,
        reasoning=reason,
    )
