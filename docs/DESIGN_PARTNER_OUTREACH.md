# Design-Partner Outreach

## Short cold email

**Subject:** Behavioral compatibility testing for your agent-facing API

Hi {{name}},

I'm building AgentSEO, a CI check for APIs and MCP servers used by AI agents. It runs the same
behavioral contracts against the target-branch and pull-request interfaces with real models, then
flags reliability, safety, tool-selection, latency, and cost regressions.

In our working demo, the OpenAPI paths and schemas remain compatible while Claude and Gemini change
tool behavior enough to block the PR. I'm looking for API/MCP teams willing to walk through their
release workflow and critique a 10-minute demo. Would a 30-minute technical conversation be useful?

## GitHub maintainer message

Hi—I'm working on AgentSEO, behavioral compatibility CI for agent-facing APIs and MCP servers. It
compares a PR interface with its baseline by running model-independent contracts through real agents
and deterministic state checks. The goal is to catch wrong-tool, safety, reliability, latency, and cost
regressions that OpenAPI schema checks cannot see.

I'm speaking with maintainers whose tools are used by external agents. Would you be open to a short
technical walkthrough of how you test tool-interface changes today? No integration is required for the
conversation.

## LinkedIn message

I'm building AgentSEO, a CI check for APIs/MCP servers operated by AI agents. It tests baseline and PR
interfaces with the same real models and behavioral contracts, then reports regressions that normal
schema compatibility misses. I'm looking for technical design partners to pressure-test the workflow.
Would you be open to a 30-minute product and release-process conversation?

## 30-second verbal pitch

AgentSEO is behavioral compatibility CI for agent-facing APIs and MCP servers—think BrowserStack for
software operated by AI agents. A normal API check tells you that paths and schemas are still valid.
AgentSEO runs the baseline and proposed interface against the same real models, state, and behavioral
contracts, then reports wrong-tool, safety, reliability, latency, and cost regressions on the PR. In our
demo the wire API remains compatible, but Claude and Gemini change behavior and the check blocks the
release.

## Two-minute product explanation

Teams increasingly expose APIs and MCP tools to agents, but the interface is more than its JSON
schema. Tool names, descriptions, parameter wording, and boundaries between similar actions influence
what a model selects. A structurally compatible edit can therefore change production behavior without
breaking an SDK or a conventional contract test.

AgentSEO treats that as a compatibility problem. A team defines small, model-independent behavioral
contracts: the user intent, initial state, required final state, forbidden side effects, clarification
expectation, and tool-call budget. In CI, AgentSEO normalizes the target and PR OpenAPI interfaces,
shows the semantic changes, and runs each contract against both sides with the same model, provider
configuration, resettable state, and deterministic evaluator.

The PR report shows success and safety changes by model, selected tools, new failure categories,
tokens, latency, estimated cost, and the transparent policy rule behind PASS, WARNING, or FAIL. A
guarded estimate prevents a run from starting above the configured budget, and hashes make the
interface, task suite, evaluator, models, and commits auditable.

The current product is a Phase 2A MVP for technical design partners. It does not automatically optimize
interfaces or replace broader production observability. We want to learn where behavioral compatibility
fits into real release processes, which regressions teams would block, and what CI latency and cost are
acceptable.
