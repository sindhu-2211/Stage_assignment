"""
ReplayProvider: serves pre-recorded LLM responses from sample_run/llm_cache.jsonl.
Zero API key required. Used by evaluators via MODEL_PROVIDER=replay.
"""
import json
from pathlib import Path
from src.providers.base import ModelProvider, DecisionDraft, ProviderError
from src.providers.gemini import _parse_response


class ReplayProvider(ModelProvider):
    def __init__(self, cache_path: Path):
        self._cache: dict[str, str] = {}
        if not cache_path.exists():
            # Empty cache — will raise on any decide() call with a helpful message
            return
        with open(cache_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                self._cache[entry["trigger_event_id"]] = entry["raw_response"]

    def decide(self, viewer_brief_json: dict, trigger_event_id: str) -> DecisionDraft:
        if trigger_event_id not in self._cache:
            raise KeyError(
                f"ReplayProvider: no cached response for trigger_event_id={trigger_event_id}. "
                "Run once with MODEL_PROVIDER=gemini to populate sample_run/llm_cache.jsonl, "
                "or set MODEL_PROVIDER=gemini and provide GOOGLE_API_KEY."
            )
        raw = self._cache[trigger_event_id]
        return _parse_response(raw, trigger_event_id)
