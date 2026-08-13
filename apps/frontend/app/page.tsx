"use client";

import Link from "next/link";
import {useEffect, useState} from "react";
import {Metric, PageTitle} from "@/components/ui";
import {getJSON, type Project, type Run} from "@/lib/api";

export default function Dashboard() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {getJSON<Project[]>("/api/projects").then(async value => {setProjects(value); const nested = await Promise.all(value.slice(0, 5).map(project => getJSON<Run[]>(`/api/projects/${project.id}/benchmark-runs`))); setRuns(nested.flat().slice(0, 8));}).catch(error => setError(String(error)));}, []);
  return <>
    <PageTitle eyebrow="Behavioral compatibility CI" title="Catch agent-breaking API changes before they ship" description="Compare baseline and pull-request interfaces against identical behavioral contracts, real model agents, resettable sandboxes, and deterministic evaluators." action={<Link href="/compatibility" className="btn-primary">Compatibility runs</Link>} />
    <section className="mb-8 grid gap-4 md:grid-cols-4"><Metric label="Projects" value={projects.length} /><Metric label="Recent runs" value={runs.length} /><Metric label="Completed" value={runs.filter(run => run.status === "COMPLETED").length} /><Metric label="Safety" value="Sandboxed" note="Production APIs are never called" /></section>
    {error && <div className="mb-6 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">API unavailable: {error}</div>}
    <div className="grid gap-8 lg:grid-cols-[1.3fr_1fr]">
      <section className="card overflow-hidden"><div className="flex items-center justify-between border-b p-5"><h2 className="font-semibold">Projects</h2><span className="text-xs text-slate-400">{projects.length} total</span></div>{projects.length ? <div className="divide-y">{projects.map(project => <Link href={`/projects/${project.id}`} key={project.id} className="flex items-center justify-between p-5 hover:bg-slate-50"><div><p className="font-semibold">{project.name}</p><p className="mt-1 text-sm text-slate-500">{project.description || `${project.sandbox_domain} sandbox`}</p></div><span className="text-slate-400">→</span></Link>)}</div> : <div className="p-10 text-center text-sm text-slate-500">No projects yet. Upload an OpenAPI spec to begin.</div>}</section>
      <section className="card overflow-hidden"><div className="border-b p-5"><h2 className="font-semibold">Recent benchmarks</h2></div>{runs.length ? <div className="divide-y">{runs.map(run => <Link href={`/runs/${run.id}`} key={run.id} className="flex items-center justify-between p-4 hover:bg-slate-50"><div><p className="text-sm font-medium">{run.provider}:{run.model}</p><p className="mt-1 text-xs text-slate-500">{run.synthetic ? "Synthetic Demo Results" : "Provider run"}</p></div><span className="rounded-lg bg-indigo-50 px-3 py-1 text-sm font-bold text-accent">{Number(run.aggregate_metrics.compatibility_score || 0).toFixed(0)}</span></Link>)}</div> : <div className="p-10 text-center text-sm text-slate-500">Runs will appear here.</div>}</section>
    </div>
  </>;
}

