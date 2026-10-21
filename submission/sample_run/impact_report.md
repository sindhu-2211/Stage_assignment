# Impact Report

## Agent Goal Success Rates

| Goal | Decisions | Successes | Success rate |
|---|---|---|---|
| G01 | 94 | 22 | 23.4% |
| G02 | 184 | 27 | 14.7% |
| G03 | 1 | 1 | 100.0% |
| G04 | 4 | 0 | 0.0% |
| G05 | 59 | 3 | 5.1% |
| G06 | 112 | 8 | 7.1% |
| G07 | 514 | 12 | 2.3% |
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

## Per-Goal Lift (agent vs holdout organic)

Holdout organic rate = fraction of holdout-arm triggered users who organically hit
each goal's success event within the goal's window, without any agent intervention.
Lift = agent success rate − holdout organic rate.

| Goal | Agent decisions | Agent success% | Holdout n | Holdout organic% | Lift |
|---|---|---|---|---|---|
| G01 | 94 | 23.4% | 1372 | 37.8% | -14.4% |
| G02 | 184 | 14.7% | 1372 | 28.6% | -13.9% |
| G03 | 1 | 100.0% | 1372 | 40.6% | +59.4% |
| G04 | 4 | 0.0% | 1372 | 2.6% | -2.6% |
| G05 | 59 | 5.1% | 1372 | 2.6% | +2.5% |
| G06 | 112 | 7.1% | 1372 | 2.9% | +4.2% |
| G07 | 514 | 2.3% | 1372 | 50.6% | -48.3% |
| G08 | 47 | 89.4% | 1372 | 63.9% | +25.5% |
| G09 | 113 | 25.7% | 1372 | 37.8% | -12.1% |
| G12 | 1 | 0.0% | 1372 | 63.9% | -63.9% |

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
