# State transitions

Thresholds live in `config/demo-thresholds.json`; visual components consume the resulting state only. These are unitless demonstration thresholds, not validated water-depth limits.

| Fresh valid level | Initial hazard | Route treatment | Meaning |
| --- | --- | --- | --- |
| 0 ≤ level < 25 | NORMAL | Green | No current simulated hazard |
| 25 ≤ level < 50 | WATCH | Yellow with dark outline | Monitor rising water |
| 50 ≤ level < 75 | WARNING | Orange | Review local disruption risk |
| 75 ≤ level ≤ 100 | CRITICAL | Red, restrained pulse | Escalate for operator review |
| Missing, fault, unknown quality, invalid/future timestamp | UNKNOWN | Grey dashed | Insufficient trustworthy observation |
| Observation older than 30 s, or quality=stale | UNKNOWN | Grey dashed; water effect stopped | Last reading cannot establish current hazard |

An initial trustworthy observation is classified immediately. Subsequent escalation must remain at the candidate level for three seconds. Crossing higher thresholds may move directly to a higher candidate after its dwell. Recovery steps down one state at a time, after five seconds strictly below the boundary minus three: CRITICAL → WARNING below 72, WARNING → WATCH below 47, WATCH → NORMAL below 22. The engine restarts candidate timing if the candidate changes; a brief boundary oscillation therefore does not flap colours. Unknown is immediate and clears pending transition memory.

| Transport evidence | Service classification |
| --- | --- |
| Stale/unavailable service-alert feed | UNKNOWN |
| Relevant active NO_SERVICE alert | SUSPENDED for affected context |
| Relevant detour/reduced/modified service/significant delays/stop moved alert | DISRUPTED |
| Fresh trip cancellation | DISRUPTED, not full-route suspension |
| Fresh applicable trip update with ≥60 s delay | DELAYED |
| Fresh alert feed without classified disruption | NORMAL means no relevant official disruption reported |
| Missing vehicle positions | Does not imply suspension |

The synthetic official-alert scenario uses the same classification with `serviceSource=fixture` and prominent demonstration labels. It never becomes an actual official announcement. Full-route risk colouring is available only as a simulation option; the credible default highlights the local GTFS segment.
