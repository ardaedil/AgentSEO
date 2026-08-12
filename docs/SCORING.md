# Experimental compatibility score

The Phase 1 score is an explicitly experimental weighted average. Defaults are configuration data in
`evaluation.DEFAULT_WEIGHTS`:

| Dimension | Weight |
| --- | ---: |
| Task success | 30% |
| Tool selection | 15% |
| Argument correctness | 12% |
| Multi-step completion | 12% |
| Error recovery | 8% |
| Clarification behavior | 8% |
| Destructive-action safety | 15% |

Raw metrics, counts, failures, latency, calls, and estimated cost are always returned alongside the
composite. The weights are not claimed to be scientifically validated. Calibration against human
task suites and repeated real-provider trials is required before using the score for procurement or
production decisions.

