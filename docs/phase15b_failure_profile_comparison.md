# Phase 1.5B audited V0 development failure profiles

This comparison uses audited development traces only. Stored v1 scores are retained separately; the table excludes identified evaluator/normalization artifacts.

| Failure pattern | GPT-4.1-mini | Claude Sonnet 5 | Gemini 3.6 Flash |
|---|---:|---:|---:|
| Post-success / unnecessary clarification | High (50 stored rows across both categories) | Low (2 genuine rows) | Low (1 row) |
| Missing required clarification | Medium (9 rows) | None | High (11 rows) |
| Ambiguous destructive action | Medium (5 destructive-category rows, overlapping missing-clarification scenarios) | Low (1 row) | High (covered by the 11 missing-clarification rows) |
| Wrong similar tool after audit | Low / none recurring | None | None |
| Identifier-routing failure | Medium (B13/C13 recurring) | Low (one terminal B13 failure) | None |
| Recovery continuation | High (B09/B11/E09/E11/C11) | None | Low (one B11 row) |
| Repeated identical failed call | None | None | None |
| Max-iteration behavior | None | None | None |
| Semantic argument omission | Low | None | Low (one E18 row) |

Audited success was 60.0% GPT, 98.1% Claude, and 91.9% Gemini. The fresh benchmark therefore avoided a ceiling for GPT, but not for Claude and only weakly for Gemini. This calibration outcome is preserved rather than manipulating task difficulty after observing model results.

