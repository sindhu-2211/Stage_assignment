"""NVIDIA NIM provider — OpenAI-compatible API, free tier available."""
import json
import time
import requests
from src.providers.base import ModelProvider, DecisionDraft, ProviderError, ProviderTimeoutError
from src.stage2.prompt_template import build_prompt
from src.providers.gemini import _parse_response

_BASE_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
_DEFAULT_MODEL = "mistralai/mistral-7b-instruct-v0.3"


class NvidiaProvider(ModelProvider):
    def __init__(self, api_key: str, model: str = _DEFAULT_MODEL):
        self._api_key = api_key
        self._model = model

    def decide(self, viewer_brief_json: dict, trigger_event_id: str) -> DecisionDraft:
        prompt = build_prompt(viewer_brief_json)

        last_err = None
        for attempt in range(3):
            try:
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
                        "max_tokens": 512,
                    },
                    timeout=30,
                )
                if resp.status_code == 429:
                    wait = (attempt + 1) * 10
                    print(f"  [nvidia rate limit, waiting {wait}s, attempt {attempt+1}/3]")
                    time.sleep(wait)
                    last_err = f"429 rate limit"
                    continue
                if resp.status_code == 401:
                    raise ProviderError("NVIDIA API key invalid (401). Get key at https://build.nvidia.com/")
                resp.raise_for_status()
                data = resp.json()
                raw = data["choices"][0]["message"]["content"]
                if raw is None:
                    raise ProviderError("NVIDIA returned None content")
                return _parse_response(raw, trigger_event_id)
            except (requests.Timeout, requests.exceptions.Timeout):
                raise ProviderTimeoutError("NVIDIA request timed out")
            except ProviderError:
                raise
            except ProviderTimeoutError:
                raise
            except Exception as e:
                raise ProviderError(f"NVIDIA error: {e}") from e

        raise ProviderError(f"NVIDIA failed after 3 retries: {last_err}")
