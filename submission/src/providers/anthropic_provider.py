"""Anthropic Claude provider — opt-in via MODEL_PROVIDER=anthropic."""
import json
from src.providers.base import ModelProvider, DecisionDraft, ProviderError, ProviderTimeoutError
from src.stage2.prompt_template import build_prompt
from src.providers.gemini import _parse_response


class AnthropicProvider(ModelProvider):
    def __init__(self, api_key: str, model: str = "claude-haiku-5-5"):
        import anthropic
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def decide(self, viewer_brief_json: dict, trigger_event_id: str) -> DecisionDraft:
        prompt = build_prompt(viewer_brief_json)
        try:
            msg = self._client.messages.create(
                model=self._model,
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
                timeout=30.0,
            )
            raw = msg.content[0].text
        except Exception as e:
            err = str(e).lower()
            if "timeout" in err or "deadline" in err:
                raise ProviderTimeoutError(f"Anthropic timeout: {e}") from e
            raise ProviderError(f"Anthropic error: {e}") from e

        return _parse_response(raw, trigger_event_id)
