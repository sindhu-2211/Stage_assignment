# AI Collaboration Log

## Tools used

- **Claude (Anthropic)** via Claude Code CLI — used throughout development for code drafting, debugging, and documentation
- **AWS Bedrock (Llama3-8B)** — used as the LLM provider for the final sample run (zero Gemini API cost)

## How I used AI assistance

### Architecture exploration
I used Claude to think through three candidate designs: a single orchestrator, a deterministic three-stage pipeline, and a ReAct loop. The key constraint that drove the decision was the assignment's requirement for independent verification — if the same model verifies its own output, it tends to rationalise rather than catch errors. I settled on the three-stage pipeline (Stage 1: deterministic Python assembly, Stage 2: one LLM call, Stage 3: deterministic Python verification) and used Claude to pressure-test that design against the surprise scenarios in Section 6.

### Code drafting
I used Claude to draft the Python implementation across all modules. I reviewed each generated function against the data pack schema and the assignment brief before accepting it. Key things I caught and corrected during review:
- Dialect priority order needed to match the pack's README exactly
- Eligibility checks for G07 (unfinished series) needed episode-count logic that the first draft got wrong
- The frequency cap needed to track from `actions.jsonl` (what we send), not from `message_delivered` events

### Debugging
Used Claude to diagnose two runtime errors:
- `NoneType.strip()` from `app_dialect=null` in ~10 trigger events — fixed with `(value or "").strip()` guard
- Publisher writing `title_id=null` (string) when Llama returned JSON null — fixed by normalising in `_build_draft()`

### Review passes
I explicitly asked Claude to review the correctness audit of the pipeline — checking whether goal selection, dialect resolution, and verifier checks were producing correct outputs for real viewer data. Claude traced three users end-to-end against raw pack events and found two real bugs (dual "availability" in passed+failed, stale check messages). I applied both fixes.

### Documentation
I used Claude to draft README.md, ARCHITECTURE.md, and KNOWN_LIMITATIONS.md, then reviewed and edited for accuracy. The impact report methodology (holdout organic baseline, why naive comparison misleads) was written by Claude but reflects design decisions I made.

## What I did not delegate to AI

- Reading and understanding the assignment brief (I read the full PDF)
- Choosing the LLM provider for the sample run (chose Bedrock to avoid Gemini API billing)
- Deciding what counts as a known limitation vs a fixable bug
- Final review of all submitted output files

## Responsibility

All submitted work is my own. AI was used as a development tool. I reviewed, tested, and take responsibility for everything in this submission.
