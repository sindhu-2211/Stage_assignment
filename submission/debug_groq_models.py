#!/usr/bin/env python3
import os, sys, requests
key = os.environ.get("GROQ_API_KEY", "")
if not key:
    print("GROQ_API_KEY not set"); sys.exit(1)
r = requests.get("https://api.groq.com/openai/v1/models",
    headers={"Authorization": f"Bearer {key}"}, timeout=10)
print("HTTP", r.status_code)
for m in r.json().get("data", []):
    print(" ", m["id"])
