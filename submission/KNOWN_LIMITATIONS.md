# Known Limitations

## Goal measurement gaps

**G10 (meaningful_engagement_7d)** — `success_event` is `null` in `goals.json`. There is no signal in the event stream that maps to "engaged meaningfully". G10 is included in eligible goals (any viewer qualifies) but marked `measurable: false`. The outcome judge records all G10 decisions as `outcome: unverifiable`. No proxy success signal was invented — that would make the measurement meaningless.

**G11 (tv_activation_14d)** — success requires `tv_app_open` which does not appear anywhere in `events.jsonl`, `live_events.jsonl`, or the event schema in the README. G11 is excluded from eligible goals entirely. If `tv_app_open` is added to the event stream in the evaluator's unseen replay day, G11 will still not be selected (it is not in the eligibility checks) and not measured.

## Dialect coverage

**corpus_default fallback** — when a viewer has no `app_dialect`, no `preferred_dialect`, and no campaign deeplink, the agent falls back to the most common dialect in `profiles_snapshot.csv` (d1). Home-page intervention is disabled in this case because the app only serves a home page matching the app's current dialect. Push and in-app messages are still available.

**dialect="NA"** — some triggers have `app_dialect=null` or `app_dialect="NA"`. The agent treats these as "no app_setting source" and falls through to profile or corpus_default. Titles in dialect "NA" are not served (zero titles match), so the agent returns no_action for content-based interventions for these viewers.

## Profile snapshot staleness

The profile snapshot was taken at `2026-09-30T05:30 IST` — approximately 25 hours before the replay day. Purchase and subscription events between snapshot time and trigger time override the profile's `subscription_status`, but other fields (consent, platform, signup_at) use the snapshot value. A consent change that arrived after snapshot time is not reflected.

## Frequency cap tracking

The frequency cap (at most 1 push + WhatsApp per IST day) is tracked from the agent's own `actions.jsonl` — not from `message_delivered` events in the event stream. This is correct by design: the cap is on what we send, not what is confirmed delivered. However, if the agent is run in parallel with another system that also sends messages to the same users, the cap will undercount.

## G07 unfinished series — title_id to content_slug mapping

The eligibility check for G07 maps `play_started.properties.title_id` to `content_slug` via the catalogue. Titles that were in the catalogue at snapshot time but withdrawn by a `title_withdrawn` control event are removed from the live catalogue. If a viewer's only unfinished series had its title withdrawn, G07 will not be eligible for them (correct behaviour — we cannot recommend a withdrawn title).

## Latency under load

The 60-second budget is per-decision. Under high trigger volume (the replay processes ~1 trigger/second), each decision runs synchronously. No parallel processing is implemented. On the evaluator's machine, latency depends on Gemini API response time, which can spike during high demand (observed 503 errors during testing).

## LLM response quality

The prompt is designed to be compact (≤800 tokens) for compatibility with local models. Gemini 3.8 Flash occasionally returns `no_action` for viewers with clear eligible goals and available content. Stage 3 does not correct this — it only blocks unsafe actions, not missing ones. The decision is recorded as-is with the model's confidence score.
