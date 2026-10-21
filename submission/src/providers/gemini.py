"""Gemini provider via google-genai SDK with rate-limit retry."""
import json
import time
from src.providers.base import ModelProvider, DecisionDraft, ProviderError, ProviderTimeoutError
from src.stage2.prompt_template import build_prompt

# Free tier: ~15 RPM for gemini-3.5-flash-lite. Sleep 4s between calls = 15 RPM max.
_MIN_INTERVAL_S = 4.0
_last_call_time = 0.0


class GeminiProvider(ModelProvider):
    def __init__(self, api_key: str, model: str = "gemini-3.8-flash"):
        from google import genai
        from google.genai import types
        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._types = types

    def decide(self, viewer_brief_json: dict, trigger_event_id: str) -> DecisionDraft:
        global _last_call_time
        prompt = build_prompt(viewer_brief_json)

        # Rate limiting: ensure minimum interval between calls
        elapsed = time.monotonic() - _last_call_time
        if elapsed < _MIN_INTERVAL_S:
            time.sleep(_MIN_INTERVAL_S - elapsed)

        # Retry up to 3 times on 429/503
        last_err = None
        for attempt in range(3):
            try:
                _last_call_time = time.monotonic()
                response = self._client.models.generate_content(
                    model=self._model,
                    contents=prompt,
                    config=self._types.GenerateContentConfig(
                        temperature=0,
                        max_output_tokens=512,
                    ),
                )
                raw = response.text
                if raw is None:
                    raise ProviderError("Gemini returned None text (safety filter or unsupported config)")
                return _parse_response(raw, trigger_event_id)
            except Exception as e:
                err_str = str(e).lower()
                if "timeout" in err_str or "deadline" in err_str:
                    raise ProviderTimeoutError(f"Gemini timeout: {e}") from e
                if "429" in err_str or "quota" in err_str or "503" in err_str or "unavailable" in err_str:
                    wait = (attempt + 1) * 10
                    print(f"  [rate limit/503, waiting {wait}s, attempt {attempt+1}/3]: {str(e)[:120]}")
                    time.sleep(wait)
                    last_err = e
                    continue
                print(f"  [gemini error]: {type(e).__name__}: {str(e)[:200]}")
                raise ProviderError(f"Gemini error: {e}") from e

        raise ProviderError(f"Gemini failed after 3 retries: {last_err}")


_WORD_NUMS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
}


def _normalize_text(text: str) -> str:
    """Fix LLM quirks: '0. nine' → '0.9', 'zero. five' → '0.5'."""
    import re
    pattern = r'(\d+)\.\s+(' + '|'.join(_WORD_NUMS) + r')\b'
    def replace(m):
        return m.group(1) + "." + _WORD_NUMS[m.group(2)]
    return re.sub(pattern, replace, text, flags=re.IGNORECASE)


def _parse_response(raw: str, trigger_event_id: str) -> DecisionDraft:
    text = _normalize_text(raw.strip())

    # Try 1: parse as-is
    try:
        data = json.loads(text)
        return _build_draft(data, raw)
    except json.JSONDecodeError:
        pass

    # Try 2: strip markdown code fences ```json ... ``` or ``` ... ```
    if "```" in text:
        import re
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(1))
                return _build_draft(data, raw)
            except json.JSONDecodeError:
                pass

    # Try 3: extract first {...} block from anywhere in text
    import re
    m = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(0))
            return _build_draft(data, raw)
        except json.JSONDecodeError:
            pass

    raise ProviderError(f"Could not extract JSON from response.\nRaw: {raw[:300]}")

    return _build_draft(data, raw)


def _build_draft(data: dict, raw: str) -> DecisionDraft:
    # Normalize string "null" → Python None (some models emit JSON `null` as text)
    title_id = data.get("title_id")
    if isinstance(title_id, str) and title_id.lower() in ("null", "none", ""):
        title_id = None
    goal_id = data.get("goal_id")
    if isinstance(goal_id, str) and goal_id.lower() in ("null", "none", ""):
        goal_id = None
    return DecisionDraft(
        goal_id=goal_id,
        action_type=data.get("action_type", "no_action"),
        title_id=title_id,
        content_slug=data.get("content_slug"),
        row_types=data.get("row_types", []),
        confidence=float(data.get("confidence", 0.0)),
        reasoning=data.get("reasoning", ""),
        raw_response=raw,
    )
