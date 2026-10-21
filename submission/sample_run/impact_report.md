# Impact Report

## Agent Goal Success Rates

| Goal | Decisions | Successes | Success rate |
|---|---|---|---|
| G01 | 94 | 22 | 23.4% |
| G02 | 184 | 27 | 14.7% |
| G03 | 1 | 1 | 100.0% |
| G04 | 4 | 0 | 0.0% |
| G05 | 59 | 3 | 5.1% |
| G06 | 111 | 8 | 7.2% |
| G07 | 597 | 16 | 2.7% |
| G08 | 47 | 42 | 89.4% |
| G09 | 113 | 29 | 25.7% |
| G12 | 1 | 0 | 0.0% |

## Holdout Arm — Organic Conversion Baseline

Holdout arm had **1372** triggers (received no intervention).
Within 168h window, organic events observed:

| Event type | Count | Rate |
|---|---|---|
| Paid purchase (is_trial=false) | 35 | 2.6% |
| Trial start | 0 | 0.0% |
| Any play_started | 854 | 62.2% |
| No conversion | 483 | 35.2% |

> Note: holdout users are not assigned goals by the agent (by design), so per-goal
> comparison is not possible. Agent success rates above are goal-specific and represent
> users who were eligible, received a targeted intervention, and hit the success event.
> The holdout table gives the organic baseline: what fraction of triggered-but-unserved
> users converted within the same 168h window without any agent message.

## Why naive comparison misleads

A naive comparison (agent-served users vs all users) overstates lift because:

1. **Selection bias**: agent only acts on users who triggered (app_open/login).
   Holdout users also triggered but received no intervention — correct baseline.
2. **Eligibility confound**: user served G01 (new user, no plays) is inherently
   different from average user. Comparing to everyone mixes eligibility tiers.
3. **Randomized holdout removes confounds**: arms.csv randomizes before replay day,
   so agent-arm and holdout-arm users have same prior distribution.
   Only difference is whether our agent acted.

## Measurement notes

- G10 (meaningful_engagement): excluded — success_event=null.
- G11 (tv_activation_14d): excluded — tv_app_open absent from event schema.
- Outcome window starts at deliver_at (trigger time), not action send_at.
- 'inconclusive' = window not elapsed or insufficient signal in simulator output.
- Agent arm size and holdout arm size differ; rates computed per-arm, not raw counts.
