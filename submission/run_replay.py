#!/usr/bin/env python3
"""
Entry point: run the agent against replay/triggers.jsonl.

Usage:
    python run_replay.py --pack <path-to-data-pack> [--provider gemini|anthropic|ollama|replay]
    MODEL_PROVIDER=replay python run_replay.py --pack <path>

Provider selection (first match wins):
    1. --provider flag
    2. MODEL_PROVIDER env var
    3. GOOGLE_API_KEY set → gemini
    4. default → replay (no API key required)
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.config import AgentConfig
from src.live_state import LiveState
from src.providers import build_provider
from src.harness.replay import run_replay


def main():
    parser = argparse.ArgumentParser(description="OTT Viewer Lifecycle Agent — Replay Runner")
    parser.add_argument("--pack", required=True, help="Path to the one_user_one_agent_pack directory")
    parser.add_argument(
        "--provider",
        choices=["gemini", "anthropic", "ollama", "replay", "rulebased", "nvidia", "groq", "bedrock"],
        default=None,
        help="LLM provider (default: auto-detect from env)",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Output directory (default: sample_run/ next to this file)",
    )
    args = parser.parse_args()

    pack_root = Path(args.pack).resolve()
    if not pack_root.is_dir():
        print(f"ERROR: pack path does not exist: {pack_root}", file=sys.stderr)
        sys.exit(1)

    out_dir = Path(args.out).resolve() if args.out else Path(__file__).parent / "sample_run"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "sim").mkdir(exist_ok=True)

    if args.provider:
        os.environ["MODEL_PROVIDER"] = args.provider

    print(f"Loading pack from: {pack_root}")
    config = AgentConfig(pack_root)
    print(f"  Default dialect: {config.default_dialect}")
    print(f"  Goals: {len(config.goals)}")
    print(f"  Titles: {len(config.catalogue_by_id)}")
    print(f"  Profiles: {sum(len(v) for v in config.profiles_raw.values())} rows for {len(config.profiles_raw)} users")
    print(f"  Arms: {len(config.arms)} users")

    provider = build_provider(config, out_dir)
    print(f"  Provider: {provider.__class__.__name__}")

    live_state = LiveState(config)

    run_replay(
        pack_root=pack_root,
        config=config,
        live_state=live_state,
        provider=provider,
        out_dir=out_dir,
    )


if __name__ == "__main__":
    main()
