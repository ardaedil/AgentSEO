"use client";

import {use, useEffect, useState} from "react";
import {Metric, PageTitle} from "@/components/ui";
import {getJSON, type CompatibilityRun} from "@/lib/api";

export default function CompatibilityRunPage({params}: {params: Promise<{id: string}>}) {
  const {id} = use(params);
  const [run, setRun] = useState<CompatibilityRun | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { getJSON<CompatibilityRun>(`/api/compatibility-runs/${id}`).then(setRun).catch(value => setError(String(value))); }, [id]);
  if (error) return <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-red-700">{error}</div>;
  if (!run) return <p className="text-slate-500">Loading compatibility run...</p>;
  const results = run.results || [];
  const regressions = results.filter(result => result.regression_type && result.regression_type !== "RESOLVED_FAILURE");
  const safetyRegressions = results.filter(result => result.safety_baseline && !result.safety_candidate);
  const modelMetrics = Object.entries(run.metadata.metrics?.per_model || {});
  const diff = run.metadata.interface_diff_summary;
  return <>
    <PageTitle eyebrow="Baseline vs candidate" title={run.release_classification || run.status} description={`${run.repository}: ${run.base_ref} to ${run.candidate_ref}`} />
    <section className="mb-8 grid gap-4 md:grid-cols-4"><Metric label="Verdict" value={run.verdict || "-"} /><Metric label="Interface changes" value={diff?.change_count || 0} /><Metric label="Regressed tasks" value={regressions.length} /><Metric label="Actual cost" value={`$${run.actual_cost.toFixed(4)}`} /></section>
    <section className="card mb-8 overflow-x-auto p-5"><h2 className="mb-4 font-semibold">Baseline vs candidate</h2><table className="w-full min-w-[760px] text-left text-sm"><thead className="text-xs uppercase text-slate-500"><tr><th className="pb-3">Model</th><th>Base</th><th>Candidate</th><th>Reliability</th><th>Safety</th><th>Tokens</th><th>Latency</th><th>Cost</th></tr></thead><tbody>{modelMetrics.map(([model, values]) => <tr key={model} className="border-t"><td className="py-3 font-semibold">{model}</td><td>{(values.baseline.task_success_rate * 100).toFixed(1)}%</td><td>{(values.candidate.task_success_rate * 100).toFixed(1)}%</td><td>{(values.delta.reliability * 100).toFixed(1)} pp</td><td>{(values.delta.safety * 100).toFixed(1)} pp</td><td>{values.delta.tokens.toFixed(0)}</td><td>{values.delta.latency.toFixed(2)}s</td><td>${values.delta.cost.toFixed(4)}</td></tr>)}</tbody></table></section>
    <div className="grid gap-8 lg:grid-cols-2">
      <section className="card p-5"><h2 className="mb-4 font-semibold">Interface diff</h2>{Object.entries(diff?.by_type || {}).map(([kind, count]) => <div key={kind} className="flex justify-between border-b py-2 text-sm"><span>{kind.replaceAll("_", " ")}</span><strong>{count}</strong></div>)}</section>
      <section className="card p-5"><h2 className="mb-4 font-semibold">Regressed tasks</h2>{regressions.length ? regressions.map(result => <div key={result.id} className="mb-3 rounded-lg border border-red-100 bg-red-50 p-3 text-sm"><strong>{String(result.details.task_name || result.task_id)}</strong><p className="mt-1 text-red-700">{result.regression_type}: {result.baseline_failure || "PASS"} to {result.candidate_failure || "PASS"}</p></div>) : <p className="text-sm text-slate-500">No behavioral regressions.</p>}</section>
      <section className="card p-5 lg:col-span-2"><h2 className="mb-4 font-semibold">Safety regressions</h2>{safetyRegressions.length ? safetyRegressions.map(result => <p key={result.id} className="border-t py-2 text-sm text-red-700">{String(result.details.task_name || result.task_id)} ({result.model})</p>) : <p className="text-sm text-slate-500">No safety regressions.</p>}</section>
    </div>
  </>;
}
