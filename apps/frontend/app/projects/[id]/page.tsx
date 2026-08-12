"use client";

import Link from "next/link";
import {useParams} from "next/navigation";
import {useEffect, useState} from "react";
import {Metric, PageTitle, ProjectNav} from "@/components/ui";
import {getJSON, type Project, type Run, type Task, type Tool} from "@/lib/api";

export default function ProjectOverview() {
  const id = useParams<{id: string}>().id;
  const [project, setProject] = useState<Project>(); const [tools, setTools] = useState<Tool[]>([]); const [tasks, setTasks] = useState<Task[]>([]); const [runs, setRuns] = useState<Run[]>([]);
  useEffect(() => {Promise.all([getJSON<Project>(`/api/projects/${id}`), getJSON<Tool[]>(`/api/projects/${id}/tools`), getJSON<Task[]>(`/api/projects/${id}/tasks`), getJSON<Run[]>(`/api/projects/${id}/benchmark-runs`)]).then(([p, t, ts, r]) => {setProject(p); setTools(t); setTasks(ts); setRuns(r);});}, [id]);
  return <><ProjectNav id={id} /><PageTitle eyebrow={project?.sandbox_domain || "Project"} title={project?.name || "Loading project…"} description={project?.description || "Measure interface reliability across model providers."} action={<Link href={`/projects/${id}/benchmark`} className="btn-primary">Run benchmark</Link>} />
    <div className="mb-8 grid gap-4 md:grid-cols-4"><Metric label="Discovered tools" value={tools.length} /><Metric label="Destructive tools" value={tools.filter(x => x.is_destructive).length} /><Metric label="Enabled tasks" value={tasks.filter(x => x.enabled).length} /><Metric label="Benchmark runs" value={runs.length} /></div>
    <div className="grid gap-6 md:grid-cols-3"><Link href={`/projects/${id}/tools`} className="card p-6 hover:border-accent"><p className="eyebrow">01</p><h2 className="mt-2 font-semibold">Inspect interface</h2><p className="mt-2 text-sm text-slate-500">Review normalized operations, schemas, authentication, and destructive-action inference.</p></Link><Link href={`/projects/${id}/tasks`} className="card p-6 hover:border-accent"><p className="eyebrow">02</p><h2 className="mt-2 font-semibold">Review benchmark</h2><p className="mt-2 text-sm text-slate-500">Generate, edit, disable, or add deterministic tasks before running models.</p></Link><Link href={`/projects/${id}/report`} className="card p-6 hover:border-accent"><p className="eyebrow">03</p><h2 className="mt-2 font-semibold">Compare models</h2><p className="mt-2 text-sm text-slate-500">See raw metrics, experimental score, failure categories, cost, and latency.</p></Link></div>
  </>;
}

