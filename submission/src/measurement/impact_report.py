"""
Impact report: compare agent-arm success rates vs holdout baseline.
Explains why naive comparison (served vs everyone) misleads.
"""
import json
from collections import defaultdict
from pathlib import Path


def generate_impact_report(
    outcomes: list[dict],
    arms: dict,  # user_id -> arm
    out_path: Path,
    holdout_by_goal: dict | None = None,
) -> dict:
    """
    Writes impact_report.md and returns summary dict.
    """
    # Split by arm
    agent_by_goal: dict[str, dict] = defaultdict(lambda: {"decisions": 0, "succeeded": 0})
    holdout_organic_counts: dict[str, int] = defaultdict(int)
    holdout_total_triggers = 0

    for o in outcomes:
        uid = o["viewer_id"]
        arm = arms.get(uid, "agent")

        if arm == "holdout" or o["outcome"] == "holdout":
            holdout_total_triggers += 1
            ho_type = o.get("holdout_organic", "holdout_no_conversion")
            holdout_organic_counts[ho_type] += 1
            continue

        goal = o.get("goal_id")
        if not goal or o["outcome"] in ("no_goal", "unverifiable"):
            continue

        agent_by_goal[goal]["decisions"] += 1
        if o["outcome"] == "succeeded":
            agent_by_goal[goal]["succeeded"] += 1

    rows = []
    for goal_id in sorted(agent_by_goal.keys()):
        ag = agent_by_goal[goal_id]
        agent_rate = ag["succeeded"] / ag["decisions"] if ag["decisions"] > 0 else 0.0
        rows.append({
            "goal_id": goal_id,
            "agent_decisions": ag["decisions"],
            "agent_successes": ag["succeeded"],
            "agent_success_rate": round(agent_rate, 3),
        })

    # Compute holdout organic rates
    holdout_purchases = holdout_organic_counts.get("holdout_organic_purchase", 0)
    holdout_trials = holdout_organic_counts.get("holdout_organic_trial", 0)
    holdout_plays = holdout_organic_counts.get("holdout_organic_play", 0)
    holdout_none = holdout_organic_counts.get("holdout_no_conversion", 0)
    ho_n = holdout_total_triggers or 1

    # Write markdown report
    lines = [
        "# Impact Report\n",
        "## Agent Goal Success Rates\n",
        "| Goal | Decisions | Successes | Success rate |",
        "|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['goal_id']} | {r['agent_decisions']} | {r['agent_successes']} "
            f"| {r['agent_success_rate']:.1%} |"
        )

    lines += [
        "",
        "## Holdout Arm — Organic Conversion Baseline",
        "",
        f"Holdout arm had **{holdout_total_triggers}** triggers (received no intervention).",
        "Within 168h window, organic events observed:",
        "",
        "| Event type | Count | Rate |",
        "|---|---|---|",
        f"| Paid purchase (is_trial=false) | {holdout_purchases} | {holdout_purchases/ho_n:.1%} |",
        f"| Trial start | {holdout_trials} | {holdout_trials/ho_n:.1%} |",
        f"| Any play_started | {holdout_plays} | {holdout_plays/ho_n:.1%} |",
        f"| No conversion | {holdout_none} | {holdout_none/ho_n:.1%} |",
        "",
    ]

    # Per-goal lift table
    if holdout_by_goal:
        lines += [
            "## Per-Goal Lift (agent vs holdout organic)",
            "",
            "Holdout organic rate = fraction of holdout-arm triggered users who organically hit",
            "each goal's success event within the goal's window, without any agent intervention.",
            "Lift = agent success rate − holdout organic rate.",
            "",
            "| Goal | Agent decisions | Agent success% | Holdout n | Holdout organic% | Lift |",
            "|---|---|---|---|---|---|",
        ]
        for r in rows:
            gid = r["goal_id"]
            ho = holdout_by_goal.get(gid, {})
            ho_eligible = ho.get("eligible", 0)
            ho_succeeded = ho.get("organic_succeeded", 0)
            ho_rate = ho_succeeded / ho_eligible if ho_eligible > 0 else 0.0
            lift = r["agent_success_rate"] - ho_rate
            lift_str = f"+{lift:.1%}" if lift >= 0 else f"{lift:.1%}"
            lines.append(
                f"| {gid} | {r['agent_decisions']} | {r['agent_success_rate']:.1%} "
                f"| {ho_eligible} | {ho_rate:.1%} | {lift_str} |"
            )
        lines.append("")
    else:
        lines += [
            "> Holdout organic rates not computed. Re-run generate_reports.py with --pack to",
            "> enable per-goal lift calculation.",
            "",
        ]

    lines += [
        "## Why naive comparison misleads",
        "",
        "A naive comparison (agent-served users vs all users) overstates lift because:",
        "",
        "1. **Selection bias**: agent only acts on users who triggered (app_open/login).",
        "   Holdout users also triggered but received no intervention — correct baseline.",
        "2. **Eligibility confound**: user served G01 (new user, no plays) is inherently",
        "   different from average user. Comparing to everyone mixes eligibility tiers.",
        "3. **Randomized holdout removes confounds**: arms.csv randomizes before replay day,",
        "   so agent-arm and holdout-arm users have same prior distribution.",
        "   Only difference is whether our agent acted.",
        "",
        "## Measurement notes",
        "",
        "- G10 (meaningful_engagement): excluded — success_event=null.",
        "- G11 (tv_activation_14d): excluded — tv_app_open absent from event schema.",
        "- Outcome window starts at deliver_at (trigger time), not action send_at.",
        "- 'inconclusive' = window not elapsed or insufficient signal in simulator output.",
        "- Agent arm size and holdout arm size differ; rates computed per-arm, not raw counts.",
    ]

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    summary = {
        "rows": rows,
        "holdout_total_triggers": holdout_total_triggers,
        "holdout_organic_purchases": holdout_purchases,
        "holdout_organic_trials": holdout_trials,
        "holdout_organic_plays": holdout_plays,
        "total_agent_decisions": sum(r["agent_decisions"] for r in rows),
        "total_agent_successes": sum(r["agent_successes"] for r in rows),
        "goals_measured": len(rows),
    }
    return summary
