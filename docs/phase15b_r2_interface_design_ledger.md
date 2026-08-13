# Phase 1.5B R2 human interface design ledger

The R2 interfaces were designed only from the 84-task V0 development run. The sealed holdout was neither read nor executed. The machine-readable mutation ledger is `artifacts/phase15b_r2/frozen_interfaces/mutation_ledger.json`.

## Recurring development evidence

| Failure mechanism | Affected models | Trace evidence | Interface hypothesis |
|---|---|---|---|
| Post-success clarification | Mostly GPT; some Claude | 16 failures, commonly after successful customer, invoice, subscription, shipment, or opportunity reads | Mark lookup and mutation terminal boundaries, while preserving explicitly requested verification. |
| Unnecessary tools | All models | 13 failures from redundant discovery, repeated verification, or cross-object exploration | Add concise stop conditions and explicit negative-use boundaries. |
| Wrong tool / identifier routing | Mostly GPT; some Claude/Gemini | 7 failures involving name/email discovery, direct `cus_`/`sub_`/`inv_` routing, or owner/contact confusion | Describe identifier families and separate discovery from exact-ID operations. |
| Sequence failures | All models, strongest Gemini | 8 failures in recovery, state comparison, and preservation workflows | Expose local prerequisite and recovery transitions without encoding task-specific workflows. |
| Max iterations | Gemini only | 4 failures from identical invalid-state retries, repeated owner resolution, or over-exploration before clarification | Add no-identical-retry and early-clarification guidance tied to returned error semantics. |
| Clarification errors | All models | 7 unnecessary clarifications plus discovery-before-clarification failures classified as wrong tool | Clarify that ambiguity is assessed after discovery and that unsupported/complete outcomes should be explained rather than queried. |
| Safety boundary | GPT and Gemini | 2 residual refusal misses and 2 forbidden related-tool calls | State anti-concealment refusal and owner-versus-contact boundaries explicitly. |

Not every failure is attributed to the interface. The development ledger labels 25 observations `INTERFACE_RELATED` and 34 `LIKELY_INTERFACE_RELATED`; none of the remaining audited failures were mutated without trace evidence. Model variance and task difficulty remain alternative explanations to be measured on holdout.

## Frozen variants

| Variant | Design | Mean description tokens/domain | Examples | Main regression risk |
|---|---|---:|---:|---|
| V0 | Canonical interface | 41.7 | Unchanged | Baseline semantic ambiguity. |
| V2-General | Shared boundaries for routing, recovery, safety, and termination | 214.7 | No additions | Premature stopping in legitimate multi-step work. |
| V2-GPT | General guidance with stronger terminal and identifier routing language | 209.7 | No additions | Over-stopping or under-clarification. |
| V2-Claude | General guidance with concise unsupported-operation and post-mutation stopping rules | 225.0 | No additions | Under-verification after destructive actions. |
| V2-Gemini | General guidance with bounded retry and explicit multi-status comparison rules | 210.0 | No additions | Too-early termination after recoverable errors. |

No examples were added. Changes are description and parameter semantics only; backend behavior, schemas, sandbox state, tasks, and deterministic evaluators are unchanged across interfaces.

## Mutation-to-evidence policy

Every frozen mutation records the observed R2 failure, affected model scope, trace-based hypothesis, expected benefit, and regression risk. R1 mutations were retained only where independently justified by R2 evidence; R1 itself remains unchanged at its archive tag.

Frozen combined variant hashes:

- V0: `1b62b7783efca19e57659ecb5223e5b9a1f541ca94f7d36de8d9dc6c67458489`
- V2-General: `5114f2c431b137d794f96f59dab7184604ea6dece2d8e6ba5bfdcaf2d8b88fea`
- V2-GPT: `0fd981a634b6c1d3233f0e6923d17bdee5ca1f97be41153a104b74b2db7f7418`
- V2-Claude: `01a62187f63ebdc48f9ebc14fb8e855347e18da65c45755775b420068b7e6148`
- V2-Gemini: `62640b081fd2379f66b193d008be6e956a12d554ff790647181db02ac9fc92cc`

Interface freeze SHA-256: `b905b769f25f56c7a8f8057d085494d9d7b2d2285c2084485bfa93fc50847a34`.
