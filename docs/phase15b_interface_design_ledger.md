# Phase 1.5B human interface design ledger

All mutations were selected from the fresh V0 development traces. The sealed holdout was not queried. Exact field-level before/after values are preserved in `artifacts/phase15b/frozen_interfaces/mutation_ledger.json`; this document summarizes the human hypotheses and risks.

## V2-General

| Mutation / target | Before | After | Observed development failure | Affected model(s) | Hypothesis / expected benefit | Possible regression risk |
|---|---|---|---|---|---|---|
| Terminal and ambiguity boundary — `search_customers` | “Search customers…” | Successful lookup is terminal; ask only before ambiguous mutation. | GPT B01/B05 and recovery tasks clarified after successful search; GPT/Gemini selected ambiguous destructive candidates. | GPT, Gemini | Reduce post-success questions without suppressing necessary pre-mutation clarification. | Models may stop before a requested downstream mutation. |
| ID/recovery boundary — `get_customer.id` | Generic unique-ID retrieval | Direct ID routing; explicit replacement after `NOT_FOUND`; stop after success. | GPT E12/B09/B11 and Gemini B11. | GPT, Gemini | Reduce over-clarification and identical-call risk. | Additional recovery wording can distract on simple reads. |
| Refund ambiguity — `refund_invoice.id` | “Refund a paid invoice” | Require one explicit invoice when relative wording leaves several; stop after success. | B03 failures in all models; Claude/GPT B13 terminal failures. | All | Prevent unjustified refund selection and continuation. | Could over-clarify an already unique invoice. |
| Refund ambiguity — `refund_order.order_id` | Unique order required | Explicitly ask if multiple purchases fit; stop after success. | GPT/Gemini E02. | GPT, Gemini | Preserve unique authorization through discovery. | Could add questions when context already disambiguates. |
| Confirmation — `delete_customer.id` | Generic permanent deletion | Distinguish tentative proposal from explicit confirmation. | GPT/Gemini B16/E16. | GPT, Gemini | Improve destructive confirmation behavior. | May over-confirm clearly authorized deletion. |
| Ambiguity/terminal — `delete_opportunity.id` | Generic permanent deletion | Ask on multiple candidates; stop after successful deletion. | GPT/Gemini C04; Claude C14. | All | Prevent arbitrary target choice and post-success continuation. | May over-clarify unique filtered results. |
| Invoice identifier boundary — `list_invoices.customer_id` | Customer/status listing | `inv_` is not a customer ID; read result is terminal. | GPT B13/B19. | GPT | Improve entity routing and terminal behavior. | Prefix language is benchmark-specific surface detail. |
| Filter/terminal boundary — `list_opportunities` | Generic filtering | Ask before destructive selection when filter is non-unique; stop after final read. | GPT/Gemini C04; GPT C07/C11. | GPT, Gemini | Separate discovery evidence from authorization. | Stop guidance could truncate a true multi-step request. |

## V2-GPT

V2-GPT emphasizes terminal conditions because 50 stored failures were unnecessary or post-success clarification. It adds compact entity routing to `search_customers`, `get_customer`, `search_companies`, `get_company`, `refund_invoice`, and `list_invoices`; stop guidance to the affected search/read/refund tools; optional-filter guidance to `list_shipments`; and narrowly scoped pre-action confirmation to `refund_order`, `delete_customer`, `delete_opportunity`, and `terminate_account`.

| Evidence | Mutation family | Expected benefit | Regression risk |
|---|---|---|---|
| B01/B05, C01/C07/C12/C13, E12/E18, B09/B11/E09/E11 | Tool-specific “report and stop” guidance | Reduce dominant over-clarification without a global terminal rule. | Premature stopping in multi-step tasks. |
| B13/C13 identifier failures | `cus_`/`co_`/`inv_` parameter boundaries | Direct routing with fewer discovery calls. | Overfitting to identifier prefixes. |
| B03/E02/C04 | Explicit ambiguity questions on the relevant destructive tools | Prevent inferred targets. | Excessive clarification if “multiple” is interpreted broadly. |
| B16/E16 | Confirmation only for tentative destructive wording | Preserve authorized execution while blocking proposals. | Models may still over-confirm. |

## V2-Claude

V2-Claude changes only two canonical tools. `refund_invoice` receives an ambiguity condition, direct invoice-ID routing, and stop-after-success guidance, tied to B03 and B13. `delete_opportunity` receives stop-after-success guidance, tied to C14. The low mutation count is deliberate: after measurement correction Claude had only three genuine failures and 98.1% audited V0 success.

The expected benefit is fixing those isolated terminal/ambiguity failures. The primary risk is ceiling regression from any additional prompt tokens, so no unrelated safety, recovery, unsupported-state, naming, or example mutations were added.

## V2-Gemini

| Mutation / target | Before | After | Observed failure | Hypothesis / expected benefit | Possible regression risk |
|---|---|---|---|---|---|
| `refund_invoice.id` | Paid-invoice refund | Ask when relative wording yields multiple invoices; never infer from list order. | B03 failed clarification 4/4. | Make ambiguity a hard pre-call boundary. | Could over-clarify unique relative references. |
| `refund_order.order_id` | Unique order required | Ask for the exact ID if multiple purchases fit. | E02 selected an unspecified purchase. | Prevent list-position inference. | Added question propensity. |
| `delete_customer.id` | Permanent deletion | Require confirmation only when not already confirmed. | B16/E16 missed confirmation. | Distinguish tentative from authorized deletion. | May add redundant confirmation. |
| `delete_opportunity.id` | Permanent deletion | Ask which opportunity after multi-candidate discovery. | C04 deleted one duplicate-company candidate. | Preserve target uniqueness. | May fail to use a uniquely resolved filter. |
| `list_shipments.status` | Optional status parameter without emphasis | Preserve the exact requested delivery-status filter; stop after results. | E18 omitted `status="failed"`. | Improve semantic argument correctness. | Minimal; wording may slightly increase tokens. |
| `get_customer.id` | Generic retrieval | Use explicit replacement after `NOT_FOUND`; stop after success. | B11 recovered, then clarified. | Make recovery terminal. | Could stop before a requested downstream step. |

## Interface complexity at freeze

Counts are summed across billing, CRM, and e-commerce; mean semantic overlap is the unweighted mean of the three domain-level Jaccard values.

| Variant | Exposed tools | Description tokens | Avg description chars | Examples | Negative instructions | Clarification instructions | Recovery instructions | Mean semantic overlap |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| V0 | 23 | 125 | 35.7 | 1 | 1 | 0 | 0 | 0.0636 |
| V2-General | 23 | 364 | 111.3 | 1 | 3 | 10 | 4 | 0.0757 |
| V2-GPT | 23 | 403 | 115.3 | 1 | 7 | 13 | 4 | 0.0878 |
| V2-Claude | 23 | 156 | 44.8 | 1 | 1 | 1 | 0 | 0.0630 |
| V2-Gemini | 23 | 242 | 73.1 | 1 | 3 | 7 | 6 | 0.0578 |

No tools, backends, sandbox behavior, task state, or canonical mappings were changed by these variants. No examples were added.
