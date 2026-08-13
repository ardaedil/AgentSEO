# Design-Partner Discovery Questions

Use these as a conversation guide, not a questionnaire. Ask follow-ups in the prospect's terminology.

1. Which parts of your API or MCP server are currently used by external AI agents, if any?
2. Which agent clients, frameworks, or model families do you support or observe in production?
3. How do you test changes to tool names, descriptions, parameters, and workflow semantics today?
4. What agent-related regressions or unexpected behaviors have you encountered after interface changes?
5. What happens operationally when an agent selects the wrong tool or supplies the wrong arguments?
6. How often do agent-facing interface changes reach production, and what does the release process look like?
7. Which evaluation, contract-testing, or observability tools are part of that process today?
8. Under what conditions, if any, would a behavioral regression justify blocking a pull request or release?
9. How much additional CI latency would be workable for a behavioral compatibility check?
10. What inference-cost range per pull request or release would be workable for your team?
11. Who currently owns agent-interface reliability and safety across engineering, product, and operations?
12. What evidence, integrations, or product changes would you need before installing AgentSEO or paying for it?
