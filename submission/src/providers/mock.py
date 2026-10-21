"""
MockProvider: wraps any real provider; injects faults from model_faults.jsonl.
Always active during replay — wraps whichever real provider is configured.
"""
from src.providers.base import ModelProvider, DecisionDraft, ProviderError, ProviderTimeoutError
from src.config import AgentConfig


class MockProvider(ModelProvider):
    def __init__(self, inner: ModelProvider, config: AgentConfig):
        self._inner = inner
        self._faults = config.model_faults  # dict[trigger_event_id -> fault entry]

    def decide(self, viewer_brief_json: dict, trigger_event_id: str) -> DecisionDraft:
        fault = self._faults.get(trigger_event_id)
        if fault:
            if fault.get("fault") == "timeout":
                raise ProviderTimeoutError(
                    f"MockProvider injected timeout for trigger {trigger_event_id}"
                )
            # Return the specified model_output as a DecisionDraft
            mo = fault.get("model_output", {})
            import json
            return DecisionDraft(
                goal_id=mo.get("goal_id"),
                action_type=mo.get("action_type", "no_action"),
                title_id=mo.get("title_id"),
                confidence=float(mo.get("confidence", 0.0)),
                reasoning=mo.get("reason", "fault injected by mock provider"),
                raw_response=json.dumps(mo),
            )
        return self._inner.decide(viewer_brief_json, trigger_event_id)
