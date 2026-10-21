"""AWS Bedrock provider — uses boto3 converse API (unified across models)."""
import json
from src.providers.base import ModelProvider, DecisionDraft, ProviderError, ProviderTimeoutError
from src.stage2.prompt_template import build_prompt
from src.providers.gemini import _parse_response

_DEFAULT_MODEL = "us.meta.llama3-1-8b-instruct-v1:0"


class BedrockProvider(ModelProvider):
    def __init__(self, model: str = _DEFAULT_MODEL, region: str = "us-east-1"):
        try:
            import boto3
            self._client = boto3.client("bedrock-runtime", region_name=region)
        except ImportError:
            raise ProviderError("boto3 not installed. Run: pip install boto3")
        self._model = model

    def decide(self, viewer_brief_json: dict, trigger_event_id: str) -> DecisionDraft:
        prompt = build_prompt(viewer_brief_json)
        try:
            response = self._client.converse(
                modelId=self._model,
                messages=[{"role": "user", "content": [{"text": prompt}]}],
                inferenceConfig={"maxTokens": 512, "temperature": 0},
            )
            raw = response["output"]["message"]["content"][0]["text"]
            if not raw:
                raise ProviderError("Bedrock returned empty content")
            return _parse_response(raw, trigger_event_id)
        except ProviderError:
            raise
        except Exception as e:
            err_str = str(e)
            if "timeout" in err_str.lower() or "ReadTimeout" in err_str:
                raise ProviderTimeoutError(f"Bedrock timeout: {e}") from e
            raise ProviderError(f"Bedrock error: {e}") from e
