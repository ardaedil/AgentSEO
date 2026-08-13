# Phase 1.5B R2 final pre-holdout report

R1 is archived unchanged as `PHASE15B_R1_ARCHIVED_PRE_HOLDOUT` because V0 development performance was GPT 60.0%, Claude 98.1%, and Gemini 91.9%. The Claude/Gemini ceiling made positive optimization effects difficult to measure, and R1 recorded zero holdout runs.

R2 is frozen at 120 tasks, 40 task families, 28 development families/84 tasks, and 12 sealed families/36 tasks. All ten required behavior categories are present in holdout with zero family overlap. Difficulty distribution is 33/51/36 at levels 6/7/8.

Final audited R2 V0 development results are GPT 54/84 (64.3%), Claude 72/84 (85.7%), and Gemini 67/84 (79.8%). This provides 35.7, 14.3, and 20.2 percentage points of observed headroom respectively. Claude is slightly above the approximate target but below the explicit 90% review threshold.

The evaluator audit corrected refusal normalization, optional-filter equivalence, inclusive minimum filtering, targeted clarification, semantic name matching, recovery handling, and one precondition-call limit. Original traces are preserved and no provider calls were made for deterministic re-adjudication.

R2 V0, V2-General, V2-GPT, V2-Claude, and V2-Gemini are frozen from R2 development evidence. The full sealed-holdout matrix is preregistered at 1,620 task runs. Estimated cost is $11.81, or $14.76 guarded, so the existing $5 cap blocks launch.

No R2 holdout task has been run, no sealed task content was used in interface design, and Phase 2 has not begun.

Recommendation: `READY FOR R2 SEALED HOLDOUT` after explicit budget/execution approval.
