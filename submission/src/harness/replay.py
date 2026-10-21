"""Replay harness: feeds triggers in deliver_at order, applies control events."""
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from src.config import AgentConfig
from src.live_state import LiveState
from src.providers.base import ModelProvider
from src.stage1.assembler import assemble
from src.stage2.decision import make_decision
from src.stage3.verifier import verify
from src.output.publisher import publish_action
from src.output.recorder import record_decision


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    entries = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def _load_events_by_user(path: Path) -> dict[str, list[dict]]:
    by_user: dict[str, list[dict]] = {}
    for e in _load_jsonl(path):
        uid = e.get("user_id", "")
        by_user.setdefault(uid, []).append(e)
    return by_user


def run_replay(
    *,
    pack_root: Path,
    config: AgentConfig,
    live_state: LiveState,
    provider: ModelProvider,
    out_dir: Path,
) -> None:
    decisions_path = out_dir / "decisions.jsonl"
    actions_path = out_dir / "actions.jsonl"
    llm_cache_path = out_dir / "llm_cache.jsonl"

    # Load already-processed trigger IDs (idempotency)
    processed_ids: set[str] = set()
    if decisions_path.exists():
        for line in decisions_path.read_text().splitlines():
            if line.strip():
                try:
                    d = json.loads(line)
                    t = d.get("trigger", "")
                    processed_ids.add(t.get("event_id", "") if isinstance(t, dict) else t)
                except json.JSONDecodeError:
                    pass

    # Load all triggers
    triggers = _load_jsonl(pack_root / "replay" / "triggers.jsonl")
    triggers.sort(key=lambda t: t.get("deliver_at", ""))

    # Load live events indexed by user
    print("  Loading live events...")
    live_by_user = _load_events_by_user(pack_root / "replay" / "live_events.jsonl")

    # Load historical events indexed by user (142k lines — takes ~10s)
    print("  Loading historical events (142k lines, please wait ~10s)...")
    hist_by_user = _load_events_by_user(pack_root / "data" / "events.jsonl")
    print(f"  Loaded events for {len(hist_by_user)} users.")

    # Load control events sorted by at
    control_events = _load_jsonl(pack_root / "replay" / "control_events.jsonl")
    control_events.sort(key=lambda ce: ce.get("at", ""))
    ce_cursor = 0  # index into control_events for next unapplied event

    # Counters for sequential IDs
    decision_counter = _count_existing(decisions_path)
    action_counter = _count_existing(actions_path)

    total = len(triggers)
    skipped = 0
    processed = 0
    errors = 0

    print(f"Replaying {total} triggers...")

    for i, trigger in enumerate(triggers):
        trigger_id = trigger.get("event_id", "")
        deliver_at = trigger.get("deliver_at", "")
        user_id = trigger.get("user_id", "")

        # Idempotency: skip already-processed
        if trigger_id in processed_ids:
            skipped += 1
            continue

        # Stale trigger detection: offline-buffered bursts > 48h old are downgraded
        _event_age_s = _compute_event_age(trigger)
        _stale = _event_age_s > 172_800  # 48 hours

        # Apply control events up to deliver_at
        while ce_cursor < len(control_events):
            ce = control_events[ce_cursor]
            if ce.get("at", "") <= deliver_at:
                live_state.apply(ce)
                live_state.clear_expired_deps(deliver_at)
                ce_cursor += 1
            else:
                break

        # Collect events for this user up to deliver_at
        hist = [e for e in hist_by_user.get(user_id, []) if (e.get("received_at") or "") <= deliver_at]
        live = [e for e in live_by_user.get(user_id, []) if (e.get("received_at") or "") <= deliver_at]

        # Today's published actions for frequency cap
        today_actions = _load_today_actions(actions_path, deliver_at)

        start_mono = time.monotonic()

        try:
            # Stage 1
            brief = assemble(
                trigger_event=trigger,
                historical_events=hist,
                live_events=live,
                today_actions=today_actions,
                config=config,
                live_state=live_state,
            )

            # Stage 2 (skip for holdout or stale offline trigger)
            if not brief.holdout and _stale:
                from src.providers.base import DecisionDraft
                draft = DecisionDraft(
                    goal_id=None,
                    action_type="no_action",
                    reasoning=f"stale_trigger: event_age_s={_event_age_s} > 48h threshold",
                )
            elif not brief.holdout and live_state.model_provider_available():
                draft = make_decision(brief, provider)
            elif not brief.holdout:
                from src.providers.base import DecisionDraft
                draft = DecisionDraft(
                    goal_id=None,
                    action_type="no_action",
                    reasoning="model_provider_unavailable (control event)",
                )
            else:
                from src.providers.base import DecisionDraft
                draft = DecisionDraft(action_type="no_action", reasoning="holdout_arm")

            # Stage 3 (skip for holdout / no_action passthrough)
            if not brief.holdout and draft.action_type != "no_action":
                draft, _, _ = verify(brief, draft, config, live_state)

        except Exception as e:
            from src.providers.base import DecisionDraft
            from src.stage1.brief import ViewerBrief
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            brief = ViewerBrief(
                user_id=user_id,
                trigger_event_id=trigger_id,
                deliver_at=deliver_at,
                assembled_at=now,
                assumptions=[f"pipeline_error: {type(e).__name__}: {e}"],
            )
            draft = DecisionDraft(
                action_type="no_action",
                reasoning=f"pipeline_error: {e}",
            )
            errors += 1

        decided_in_ms = (time.monotonic() - start_mono) * 1000
        published_at = _add_ms(deliver_at, decided_in_ms)

        decision_counter += 1
        decision_id = f"D-{decision_counter:05d}"

        # Publish action
        action_id = None
        if not brief.holdout and draft.action_type != "no_action":
            action_counter += 1
            action_id = f"A-{action_counter:05d}"
            publish_action(
                brief=brief,
                draft=draft,
                config=config,
                live_state=live_state,
                actions_path=actions_path,
                action_id=action_id,
                decision_id=decision_id,
                published_at=published_at,
            )

        # Record decision
        record_decision(
            brief=brief,
            draft=draft,
            decision_id=decision_id,
            action_id=action_id,
            decided_in_ms=decided_in_ms,
            actions_path=actions_path,
            decisions_path=decisions_path,
            state_dir=out_dir / "viewer_state",
            goals=config.goals,
            trigger_event=trigger,
        )

        # Cache LLM response for replay provider
        if draft.raw_response and not brief.holdout:
            with open(llm_cache_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "trigger_event_id": trigger_id,
                    "raw_response": draft.raw_response,
                }, ensure_ascii=False) + "\n")

        processed += 1
        if (i + 1) % 100 == 0 or (i + 1) == total:
            elapsed = time.monotonic()
            print(f"  [{i+1}/{total}] processed={processed} skipped={skipped} errors={errors}")

    print(f"\nDone. {processed} decisions, {action_counter} actions, {errors} errors.")
    if skipped:
        print(f"  ({skipped} triggers skipped — already in decisions.jsonl)")


def _compute_event_age(trigger: dict) -> int:
    """Return age in seconds between received_at and deliver_at."""
    try:
        deliver = trigger.get("deliver_at", "")
        received = trigger.get("received_at", deliver)
        if not deliver or not received:
            return 0
        d1 = datetime.fromisoformat(deliver.replace("Z", "+00:00"))
        d2 = datetime.fromisoformat(received.replace("Z", "+00:00"))
        return max(0, int((d1 - d2).total_seconds()))
    except (ValueError, AttributeError):
        return 0


def _count_existing(path: Path) -> int:
    if not path.exists():
        return 0
    count = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                count += 1
    return count


def _load_today_actions(actions_path: Path, deliver_at: str) -> list[dict]:
    """Load actions published so far (for frequency cap check)."""
    if not actions_path.exists():
        return []
    from src.stage1.conflict import to_ist_date
    deliver_date = str(to_ist_date(deliver_at))
    result = []
    with open(actions_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                a = json.loads(line)
                pub = a.get("send_at") or a.get("published_at", "")
                if pub and str(to_ist_date(pub)) == deliver_date:
                    result.append(a)
            except (json.JSONDecodeError, Exception):
                pass
    return result


def _add_ms(utc_str: str, ms: float) -> str:
    from datetime import datetime, timedelta
    dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
    dt2 = dt + timedelta(milliseconds=ms)
    return dt2.isoformat().replace("+00:00", "Z")
