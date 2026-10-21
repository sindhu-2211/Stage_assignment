"""Groq provider — free tier, 1440 RPD, no credit card required."""
import json
import time
import requests
from src.providers.base import ModelProvider, DecisionDraft, ProviderError, ProviderTimeoutError
from src.stage2.prompt_template import build_prompt
from src.providers.gemini import _parse_response

_BASE_URL = "https://api.groq.com/openai/v1/chat/completions"
_DEFAULT_MODEL = "openai/gpt-oss-120b"
_MIN_INTERVAL_S = 12.0  # free tier: ~5 RPM max for large models
_last_call_time = 0.0


class GroqProvider(ModelProvider):
    def __init__(self, api_key: str, model: str = _DEFAULT_MODEL):
        self._api_key = api_key
        self._model = model

    def decide(self, viewer_brief_json: dict, trigger_event_id: str) -> DecisionDraft:
        global _last_call_time
        prompt = build_prompt(viewer_brief_json)

        # Rate limit: 30 RPM free tier
        elapsed = time.monotonic() - _last_call_time
        if elapsed < _MIN_INTERVAL_S:
            time.sleep(_MIN_INTERVAL_S - elapsed)

        last_err = None
        for attempt in range(3):
            try:
                _last_call_time = time.monotonic()
                resp = requests.post(
                    _BASE_URL,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self._model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0,
                        "max_tokens": 4096,
                    },
                    timeout=30,
                )
                if resp.status_code == 429:
                    wait = (attempt + 1) * 10
                    print(f"  [groq rate limit, waiting {wait}s, attempt {attempt+1}/3]: {resp.text[:80]}")
                    time.sleep(wait)
                    last_err = "429"
                    continue
                if resp.status_code == 401:
                    raise ProviderError("Groq API key invalid. Get free key at https://console.groq.com/")
                resp.raise_for_status()
                msg = resp.json()["choices"][0]["message"]
                raw = msg.get("content") or msg.get("reasoning") or ""
                if not raw:
                    raise ProviderError("Groq returned empty content and reasoning")
                return _parse_response(raw, trigger_event_id)
            except (requests.Timeout,):
                raise ProviderTimeoutError("Groq request timed out")
            except ProviderError:
                raise
            except ProviderTimeoutError:
                raise
            except Exception as e:
                raise ProviderError(f"Groq error: {e}") from e

        raise ProviderError(f"Groq failed after 3 retries: {last_err}")
