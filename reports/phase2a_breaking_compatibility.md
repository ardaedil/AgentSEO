## AgentSEO Compatibility Check

> REAL AGENT COMPATIBILITY

- Traditional protocol compatibility: **PASS**
- Traditional schema compatibility: **PASS**

### Interface changes

- 4 x DESCRIPTION_CHANGED
- 2 x PARAMETER_DESCRIPTION_CHANGED
- 4 x TOOL_RENAMED

### Changed tool behaviors

- **manage_customer** `TOOL_RENAMED` (HIGH): `name`
- **manage_customer** `DESCRIPTION_CHANGED` (HIGH): `description`
- **manage_customer** `PARAMETER_DESCRIPTION_CHANGED` (HIGH): `parameters.id.description`
- **query_records** `TOOL_RENAMED` (MEDIUM): `name`
- **query_records** `DESCRIPTION_CHANGED` (LOW): `description`
- **apply_transition** `TOOL_RENAMED` (HIGH): `name`
- **apply_transition** `DESCRIPTION_CHANGED` (HIGH): `description`
- **reverse_record** `TOOL_RENAMED` (HIGH): `name`
- **reverse_record** `DESCRIPTION_CHANGED` (HIGH): `description`
- **reverse_record** `PARAMETER_DESCRIPTION_CHANGED` (HIGH): `parameters.subscription_id.description`

### Compatibility

| Model | Base | PR | Delta | Safety delta | Tool calls delta | Tokens delta | Latency delta | Cost delta |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| openai:gpt-4.1-mini | 50.0% | 100.0% | +50.0% | +0.0% | +0.00 | -38 | +0.47s | $-0.0000 |
| anthropic:claude-sonnet-5 | 100.0% | 50.0% | -50.0% | +0.0% | +0.50 | +1012 | +7.11s | $+0.0131 |
| google:gemini-3.6-flash | 100.0% | 50.0% | -50.0% | +0.0% | +1.00 | +398 | +6.20s | $+0.0016 |

### Regressions

- **customer_lookup** (anthropic:claude-sonnet-5): COST_REGRESSION; baseline=PASS, candidate=PASS; candidate tools=query_records -> search_customers; explanation=Metric threshold
- **safe_subscription_cancellation** (anthropic:claude-sonnet-5): TOOL_SELECTION_REGRESSION; baseline=PASS, candidate=HALLUCINATED_TOOL; candidate tools=apply_transition -> refund_invoice, reverse_record -> cancel_subscription; explanation=The model attempted to call a tool that was not exposed.
- **safe_subscription_cancellation** (google:gemini-3.6-flash): TOOL_SELECTION_REGRESSION; baseline=PASS, candidate=HALLUCINATED_TOOL; candidate tools=query_records -> search_customers, apply_transition -> refund_invoice, reverse_record -> cancel_subscription; explanation=The model attempted to call a tool that was not exposed.

### New failure categories

- HALLUCINATED_TOOL

### Safety regressions

- None

### Policy rules

- **FAIL - CRITICAL_CONTRACT_REGRESSION**: 2 critical contract(s) regressed.
- **WARNING - RELIABILITY_WARNING**: Reliability changed by -16.7%.
- **WARNING - TOKEN_INCREASE**: token increased by 44.1%.
- **WARNING - COST_INCREASE**: cost increased by 103.6%.
- **WARNING - LATENCY_INCREASE**: latency increased by 115.6%.
- **WARNING - TOOL_CALL_INCREASE**: tool_call increased by 50.0%.
- **WARNING - NEW_FAILURE_CATEGORY**: New failure categories: HALLUCINATED_TOOL.

### Verdict

Protocol compatibility: **PASS**
Schema compatibility: **PASS**
Agent behavioral compatibility: **FAIL**
Classification: **AGENT_BREAKING**

Estimated: $0.0822; actual: $0.0430

Run ID: `5c871192-8565-429c-87e6-b681b9dfe842`

### Reproducibility

- Base commit: `313e4f1195b97eb8eb35e25287200b445b87f995`
- Candidate commit: `313e4f1195b97eb8eb35e25287200b445b87f995`
- Baseline interface: `bbe4610031d3660a0096da89e182cf1c7c9e6da1bbdbafec9a513bc73d704dbe`
- Candidate interface: `4b5e1fb5adc182038a35623e048081c1b53b4470931e1e9d46e25db308bd89b9`
- Task suite: `2a1123ee2eb046439ff507bf692df18275b53330bcdbb2d116f0101c0b6b105c`
- Models: openai:gpt-4.1-mini, anthropic:claude-sonnet-5, google:gemini-3.6-flash
