"""
Event deduplication and sorting.
Rules:
- Deduplicate by event_id; on collision keep earliest received_at (first server receipt)
- Sort by received_at ascending (trustworthy server timestamp)
- Never sort by occurred_at or sent_at (phone clock, untrustworthy)
"""


def deduplicate_and_sort(events: list[dict]) -> list[dict]:
    by_id: dict[str, dict] = {}
    for e in events:
        eid = e.get("event_id")
        if not eid:
            continue
        if eid not in by_id:
            by_id[eid] = e
        else:
            if e.get("received_at", "") < by_id[eid].get("received_at", ""):
                by_id[eid] = e
    return sorted(by_id.values(), key=lambda e: e.get("received_at", ""))
