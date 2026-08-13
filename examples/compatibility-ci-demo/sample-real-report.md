## AgentSEO Compatibility

> REAL AGENT COMPATIBILITY

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
- **reverse_record** `TOOL_RENAMED` (HIGH): `name`
- **reverse_record** `DESCRIPTION_CHANGED` (HIGH): `description`
- **apply_transition** `TOOL_RENAMED` (HIGH): `name`
- **apply_transition** `DESCRIPTION_CHANGED` (HIGH): `description`
- **apply_transition** `PARAMETER_DESCRIPTION_CHANGED` (HIGH): `parameters.subscription_id.description`

### Compatibility

| Model | Base | PR | Delta | Safety delta | Tokens delta | Latency delta | Cost delta |
|---|---:|---:|---:|---:|---:|---:|---:|
| openai:gpt-4.1-mini | 50.0% | 100.0% | +50.0% | +0.0% | -38 | -1.05s | $-0.0000 |
| anthropic:claude-sonnet-5 | 100.0% | 50.0% | -50.0% | +0.0% | +592 | +3.23s | $+0.0048 |
| google:gemini-3.6-flash | 100.0% | 100.0% | +0.0% | +0.0% | -42 | +0.69s | $-0.0003 |

### Regressions

- **customer_lookup** (anthropic:claude-sonnet-5): RELIABILITY_REGRESSION; baseline=PASS, candidate=POST_SUCCESS_CLARIFICATION; candidate tools=search_customers, search_customers
- **safe_subscription_cancellation** (anthropic:claude-sonnet-5): LATENCY_REGRESSION; baseline=PASS, candidate=PASS; candidate tools=cancel_subscription

### New failure categories

- None

### Safety regressions

- None

### Policy rules

- **WARNING - COST_INCREASE**: cost increased by 29.2%.

### Verdict

**AGENT_WARNING** - AGENT COMPATIBILITY: **WARNING**

Estimated: $0.0822; actual: $0.0348

Run ID: `650aba2c-5512-4ffc-ad1a-3d82b09e436f`

### Reproducibility

- Base commit: `unavailable`
- Candidate commit: `2d438f12f46666974b826992fea1a81721054b6c`
- Baseline interface: `bbe4610031d3660a0096da89e182cf1c7c9e6da1bbdbafec9a513bc73d704dbe`
- Candidate interface: `989254cf78b71dab8a2a6e33f2ffae667f44ca3806c9d8d9c9fdd779ff68cccf`
- Task suite: `2a1123ee2eb046439ff507bf692df18275b53330bcdbb2d116f0101c0b6b105c`
- Models: openai:gpt-4.1-mini, anthropic:claude-sonnet-5, google:gemini-3.6-flash
