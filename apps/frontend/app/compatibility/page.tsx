"use client";

import Link from "next/link";
import {useEffect, useState} from "react";
import {Metric, PageTitle} from "@/components/ui";
import {getJSON, type CompatibilityRun} from "@/lib/api";

export default function CompatibilityRunsPage() {
  const [runs, setRuns] = useState<CompatibilityRun[]>([]);
  const [error, setError] = useState("");
  useEffect(() => { getJSON<CompatibilityRun[]>("/api/compatibility-runs").then(setRuns).catch(value => setError(String(value))); }, []);
  return <>
    <PageTitle eyebrow="Compatibility CI" title="Compatibility runs" description="Baseline-versus-candidate checks with semantic interface diffs, behavioral regressions, safety changes, and cost accounting." />
    <section className="mb-8 grid gap-4 md:grid-cols-3"><Metric label="Runs" value={runs.length} /><Metric label="Breaking" value={runs.filter(run => run.release_classification === "AGENT_BREAKING").length} /><Metric label="Actual cost" value={`$${runs.reduce((sum, run) => sum + run.actual_cost, 0).toFixed(3)}`} /></section>
    {error && <div className="mb-6 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">API unavailable: {error}</div>}
    <section className="card overflow-hidden"><div className="grid grid-cols-[1.4fr_1fr_1fr_.7fr] gap-4 border-b p-4 text-xs font-bold uppercase tracking-wide text-slate-500"><span>Repository</span><span>Refs</span><span>Classification</span><span>Cost</span></div>{runs.map(run => <Link key={run.id} href={`/compatibility/${run.id}`} className="grid grid-cols-[1.4fr_1fr_1fr_.7fr] gap-4 border-b p-4 text-sm hover:bg-slate-50"><span className="font-semibold">{run.repository}</span><span>{run.base_ref} → {run.candidate_ref}</span><span>{run.release_classification || run.status}</span><span>${run.actual_cost.toFixed(3)}</span></Link>)}</section>
  </>;
}
