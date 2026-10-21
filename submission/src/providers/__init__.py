"""Provider factory: reads MODEL_PROVIDER env var, wraps result in MockProvider."""
import os
from pathlib import Path
from src.providers.base import ModelProvider
from src.providers.mock import MockProvider
from src.config import AgentConfig


def build_provider(config: AgentConfig, out_dir: Path) -> ModelProvider:
    provider_name = os.environ.get("MODEL_PROVIDER", "").lower().strip()

    # Auto-detect if not set
    if not provider_name:
        if os.environ.get("GOOGLE_API_KEY"):
            provider_name = "gemini"
        else:
            provider_name = "replay"

    if provider_name == "gemini":
        api_key = os.environ.get("GOOGLE_API_KEY", "")
        if not api_key:
            raise ValueError(
                "MODEL_PROVIDER=gemini but GOOGLE_API_KEY not set. "
                "Get a free key at https://aistudio.google.com/apikey"
            )
        model = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
        from src.providers.gemini import GeminiProvider
        inner = GeminiProvider(api_key=api_key, model=model)

    elif provider_name == "anthropic":
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise ValueError("MODEL_PROVIDER=anthropic but ANTHROPIC_API_KEY not set.")
        from src.providers.anthropic_provider import AnthropicProvider
        inner = AnthropicProvider(api_key=api_key)

    elif provider_name == "ollama":
        base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        model = os.environ.get("OLLAMA_MODEL", "llama3.1")
        from src.providers.ollama import OllamaProvider
        inner = OllamaProvider(base_url=base_url, model=model)

    elif provider_name == "replay":
        cache_path = out_dir / "llm_cache.jsonl"
        from src.providers.replay import ReplayProvider
        inner = ReplayProvider(cache_path=cache_path)

    elif provider_name == "groq":
        api_key = os.environ.get("GROQ_API_KEY", "")
        if not api_key:
            raise ValueError("MODEL_PROVIDER=groq but GROQ_API_KEY not set.")
        model = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
        from src.providers.groq_provider import GroqProvider
        inner = GroqProvider(api_key=api_key, model=model)

    elif provider_name == "nvidia":
        api_key = os.environ.get("NVIDIA_API_KEY", "")
        if not api_key:
            raise ValueError("MODEL_PROVIDER=nvidia but NVIDIA_API_KEY not set.")
        model = os.environ.get("NVIDIA_MODEL", "meta/llama-3.1-8b-instruct")
        from src.providers.nvidia import NvidiaProvider
        inner = NvidiaProvider(api_key=api_key, model=model)

    elif provider_name == "rulebased":
        from src.providers.rulebased import RuleBasedProvider
        inner = RuleBasedProvider()

    elif provider_name == "bedrock":
        model = os.environ.get("BEDROCK_MODEL", "us.meta.llama3-1-8b-instruct-v1:0")
        region = os.environ.get("AWS_DEFAULT_REGION", os.environ.get("AWS_REGION", "us-east-1"))
        from src.providers.bedrock import BedrockProvider
        inner = BedrockProvider(model=model, region=region)

    else:
        raise ValueError(f"Unknown MODEL_PROVIDER={provider_name!r}. Use: gemini|anthropic|ollama|replay|rulebased|nvidia|bedrock")

    # Always wrap in MockProvider for fault injection
    return MockProvider(inner=inner, config=config)
