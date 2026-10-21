#!/usr/bin/env python3
"""Debug: show raw Bedrock response for one trigger."""
import os, sys, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from src.config import AgentConfig
from src.live_state import LiveState
from src.stage1.assembler import assemble
from src.stage2.prompt_template import build_prompt

pack = Path("../one_user_one_agent_data_pack (4)/one_user_one_agent_pack")
config = AgentConfig(pack)
live_state = LiveState(config)
triggers = [json.loads(l) for l in open(pack / "replay/triggers.jsonl") if l.strip()]

import boto3
region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
model = os.environ.get("BEDROCK_MODEL", "us.meta.llama3-1-8b-instruct-v1:0")
client = boto3.client("bedrock-runtime", region_name=region)

for t in triggers:
    if config.arms.get(t.get("user_id")) == "agent":
        brief = assemble(trigger_event=t, historical_events=[], live_events=[],
                         today_actions=[], config=config, live_state=live_state)
        if brief.eligible_goals and brief.available_titles:
            prompt = build_prompt(brief.to_dict())
            print(f"Model: {model}, User: {brief.user_id}")
            response = client.converse(
                modelId=model,
                messages=[{"role": "user", "content": [{"text": prompt}]}],
                inferenceConfig={"maxTokens": 512, "temperature": 0},
            )
            raw = response["output"]["message"]["content"][0]["text"]
            usage = response.get("usage", {})
            input_tokens = usage.get("inputTokens", 0)
            output_tokens = usage.get("outputTokens", 0)
            print(f"Tokens — input: {input_tokens}, output: {output_tokens}")
            # Llama 3.1 8B pricing: $0.22/M input, $0.22/M output
            cost = (input_tokens * 0.22 + output_tokens * 0.22) / 1_000_000
            total_est = cost * 1397
            print(f"Cost this call: ${cost:.6f}")
            print(f"Estimated total (1397 calls): ${total_est:.4f}")
            print("RAW:")
            print(repr(raw[:500]))
            break
