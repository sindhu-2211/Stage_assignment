"""Ollama provider — opt-in via MODEL_PROVIDER=ollama."""
import json
import httpx
from src.providers.base import ModelProvider, DecisionDraft, ProviderError, ProviderTimeoutError
from src.stage2.prompt_template import build_prompt
from src.providers.gemini import _parse_response


class OllamaProvider(ModelProvider):
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama3.1"):
        self._base_url = base_url.rstrip("/")
        self._model = model

    def decide(self, viewer_brief_json: dict, trigger_event_id: str) -> DecisionDraft:
        prompt = build_prompt(viewer_brief_json)
        payload = {
            "model": self._model,
            "prompt": prompt,
            "format": "json",
            "stream": False,
            "options": {"temperature": 0},
        }
        try:
            resp = httpx.post(
                f"{self._base_url}/api/generate",
                json=payload,
                timeout=55.0,
            )
            resp.raise_for_status()
            data = resp.json()
            raw = data.get("response", "")
        except httpx.TimeoutException as e:
            raise ProviderTimeoutError(f"Ollama timeout: {e}") from e
        except Exception as e:
            raise ProviderError(f"Ollama error: {e}") from e

        return _parse_response(raw, trigger_event_id)
