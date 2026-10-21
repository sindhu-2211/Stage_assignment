#!/usr/bin/env python3
"""
Generate impact report and final report after simulator has run.

Usage:
    python3 generate_reports.py --pack <path-to-data-pack>
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.config import AgentConfig
from src.measurement.outcome_judge import judge_outcomes, compute_holdout_per_goal_organic
from src.measurement.impact_report import generate_impact_report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", required=True)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    pack_root = Path(args.pack).resolve()
    out_dir = Path(args.out).resolve() if args.out else Path(__file__).parent / "sample_run"

    decisions_path = out_dir / "decisions.jsonl"
    actions_path = out_dir / "actions.jsonl"
    outcome_events_path = out_dir / "sim" / "outcome_events.jsonl"
    impact_path = out_dir / "impact_report.md"
    final_path = out_dir / "final_report.md"
    latency_path = out_dir / "latency_report.json"

    print("Loading config...")
    config = AgentConfig(pack_root)

    print("Judging outcomes...")
    if not outcome_events_path.exists():
        print(f"WARNING: {outcome_events_path} not found. Run simulator first.")
        print("  python3 simulator/simulate_outcomes.py --pack . --actions sample_run/actions.jsonl --out sample_run/sim")
        outcomes = []
    else:
        outcomes = judge_outcomes(decisions_path, outcome_events_path, config.goals, config.catalogue_by_id)
        print(f"  {len(outcomes)} outcome records")
        outcomes_path = out_dir / "outcomes.jsonl"
        with open(outcomes_path, "w", encoding="utf-8") as f:
            for o in outcomes:
                f.write(json.dumps(o, ensure_ascii=False) + "\n")
        print(f"  Written: {outcomes_path}")

    print("Computing per-goal holdout lift...")
    holdout_by_goal = {}
    if outcome_events_path.exists():
        holdout_by_goal = compute_holdout_per_goal_organic(
            decisions_path, outcome_events_path, config.goals
        )
        print(f"  Goals with holdout organic data: {len(holdout_by_goal)}")

    print("Generating impact report...")
    summary = generate_impact_report(outcomes, config.arms, impact_path, holdout_by_goal)
    print(f"  Written: {impact_path}")

    print("Generating latency report...")
    _write_latency_report(decisions_path, latency_path)
    print(f"  Written: {latency_path}")

    print("Generating final report...")
    _write_final_report(decisions_path, actions_path, outcomes, summary, final_path)
    print(f"  Written: {final_path}")

    print("\nDone.")


def _write_latency_report(decisions_path: Path, out_path: Path):
    if not decisions_path.exists():
        return
    times = []
    failures = 0
    with open(decisions_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            ms = d.get("decided_in_ms", 0)
            times.append(ms)
            if ms > 60_000:
                failures += 1

    if not times:
        return

    times.sort()
    n = len(times)
    report = {
        "total_decisions": n,
        "latency_failures": failures,
        "p50_ms": round(times[n // 2], 1),
        "p95_ms": round(times[int(n * 0.95)], 1),
        "p99_ms": round(times[int(n * 0.99)], 1),
        "max_ms": round(times[-1], 1),
        "min_ms": round(times[0], 1),
    }
    out_path.write_text(json.dumps(report, indent=2))


def _write_final_report(decisions_path, actions_path, outcomes, impact_summary, out_path):
    decisions = []
    if decisions_path.exists():
        with open(decisions_path, encoding="utf-8") as f:
            decisions = [json.loads(l) for l in f if l.strip()]

    actions = []
    if actions_path.exists():
        with open(actions_path, encoding="utf-8") as f:
            actions = [json.loads(l) for l in f if l.strip()]

    agent = [d for d in decisions if not d.get("holdout")]
    holdout = [d for d in decisions if d.get("holdout")]

    def _goal_id(d):
        g = d.get("goal")
        return g.get("id") if isinstance(g, dict) else g

    goal_counts = Counter(_goal_id(d) for d in agent if _goal_id(d))
    action_counts = Counter(d["action"]["type"] for d in agent)
    outcome_counts = Counter(o["outcome"] for o in outcomes if not o["outcome"] == "holdout")

    lines = [
        "# Final Report\n",
        "## Summary\n",
        f"- Total triggers: {len(decisions)}",
        f"- Agent-arm decisions: {len(agent)}",
        f"- Holdout-arm (no action): {len(holdout)}",
        f"- Actions published: {len(actions)}",
        "",
        "## Goals selected (agent arm)\n",
        "| Goal | Count |",
        "|---|---|",
    ]
    for goal, cnt in goal_counts.most_common():
        lines.append(f"| {goal} | {cnt} |")

    lines += [
        "",
        "## Interventions published\n",
        "| Type | Count |",
        "|---|---|",
    ]
    for atype, cnt in action_counts.most_common():
        lines.append(f"| {atype} | {cnt} |")

    lines += [
        "",
        "## Outcome distribution\n",
        "| Outcome | Count |",
        "|---|---|",
    ]
    for outcome, cnt in outcome_counts.most_common():
        lines.append(f"| {outcome} | {cnt} |")

    ho_triggers = impact_summary.get('holdout_total_triggers', 0)
    ho_purchase = impact_summary.get('holdout_organic_purchases', 0)
    ho_play = impact_summary.get('holdout_organic_plays', 0)
    ho_n = ho_triggers or 1

    lines += [
        "",
        "## Impact (agent vs holdout)\n",
        f"See `impact_report.md` for full breakdown.",
        f"Goals measured: {impact_summary.get('goals_measured', 0)}",
        f"Total agent decisions with goal: {impact_summary.get('total_agent_decisions', 0)}",
        f"Total agent successes: {impact_summary.get('total_agent_successes', 0)}",
        f"",
        f"**Holdout organic baseline** (n={ho_triggers} triggers, no intervention):",
        f"- Organic paid purchase rate: {ho_purchase/ho_n:.1%}",
        f"- Organic play rate: {ho_play/ho_n:.1%}",
    ]

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
