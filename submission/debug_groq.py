#!/usr/bin/env python3
"""Debug: show exactly what Groq returns for one real trigger."""
import os, sys, json, requests
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from src.config import AgentConfig
from src.live_state import LiveState
from src.stage1.assembler import assemble
from src.stage2.prompt_template import build_prompt

key = os.environ.get("GROQ_API_KEY", "")
if not key:
    print("GROQ_API_KEY not set")
    sys.exit(1)

pack = Path("../one_user_one_agent_data_pack (4)/one_user_one_agent_pack")
config = AgentConfig(pack)
live_state = LiveState(config)
triggers = [json.loads(l) for l in open(pack / "replay/triggers.jsonl") if l.strip()]

found = False
for t in triggers:
    if config.arms.get(t.get("user_id")) == "agent":
        brief = assemble(trigger_event=t, historical_events=[], live_events=[],
                         today_actions=[], config=config, live_state=live_state)
        if brief.eligible_goals and brief.available_titles:
            prompt = build_prompt(brief.to_dict())
            print(f"Sending prompt for user {brief.user_id}...")
            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={"model": os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b"),
                      "messages": [{"role": "user", "content": prompt}],
                      "max_tokens": 1024, "temperature": 0},
                timeout=15,
            )
            print(f"HTTP {r.status_code}")
            data = r.json()
            if "choices" not in data:
                print("ERROR - no choices:", data)
                sys.exit(1)
            print("FULL MESSAGE OBJECT:")
            print(json.dumps(data["choices"][0]["message"], indent=2))
            raw = data["choices"][0]["message"].get("content") or ""
            print("\nCONTENT FIELD:")
            print(repr(raw))
            found = True
            break

if not found:
    print("No suitable trigger found")
