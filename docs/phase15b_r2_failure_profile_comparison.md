# Phase 1.5B R2 V0 failure-profile comparison

Only R2 development observations are included; the sealed holdout remained unopened.

- Failures by model: {'anthropic:claude-sonnet-5': 12, 'google:gemini-3.6-flash': 17, 'openai:gpt-4.1-mini': 30}
- Failures by category: {'DESTRUCTIVE_ACTION_ERROR': 2, 'FAILED_TO_REFUSE': 2, 'MAX_ITERATIONS': 4, 'POST_SUCCESS_CLARIFICATION': 16, 'TOOL_SEQUENCE_ERROR': 8, 'UNNECESSARY_CLARIFICATION': 7, 'UNNECESSARY_TOOL': 13, 'WRONG_TOOL': 7}
- Attribution hypotheses: {'INTERFACE_RELATED': 25, 'LIKELY_INTERFACE_RELATED': 34}

GPT is dominated by post-success clarification and identifier/tool routing. Claude's smaller failure set concentrates on unnecessary terminal behavior and unsupported-operation handling. Gemini is distinguished by repeated-call/max-iteration recovery failures and incomplete multi-call status comparisons. Shared unnecessary-tool failures justify a concise general variant; divergent patterns justify separately frozen model-specific variants.
