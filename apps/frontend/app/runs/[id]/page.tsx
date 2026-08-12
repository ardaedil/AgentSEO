"use client";

import Link from "next/link";
import {useParams} from "next/navigation";
import {useEffect, useState} from "react";
import {Metric, PageTitle, ScoreBar} from "@/components/ui";
import {getJSON, type Run, type TaskRun} from "@/lib/api";

export default function RunPage() {
  const id = useParams<{id: string}>().id; const [run, setRun] = useState<Run>(); const [tasks, setTasks] = useState<TaskRun[]>([]);
  useEffect(() => {Promise.all([getJSON<Run>(`/api/benchmark-runs/${id}`), getJSON<TaskRun[]>(`/api/benchmark-runs/${id}/task-runs`)]).then(([r, t]) => {setRun(r); setTasks(t);});}, [id]);
  const metrics = run?.aggregate_metrics || {}; return <><PageTitle eyebrow={run?.synthetic ? "Synthetic Demo Results" : "Provider benchmark"} title={run ? `${run.provider}:${run.model}` : "Loading benchmark…"} description={`Status: ${run?.status || "…"}. Full traces contain only visible model messages, calls, results, and evaluator output.`} action={run && <Link href={`/projects/${run.project_id}/report`} className="btn-secondary">Back to report</Link>} />
    <div className="mb-8 grid gap-4 md:grid-cols-4"><Metric label="Compatibility score" value={`${Number(metrics.compatibility_score || 0).toFixed(1)}/100`} /><Metric label="Successful tasks" value={`${metrics.successful_tasks || 0}/${metrics.task_count || 0}`} /><Metric label="Average calls" value={Number(metrics.average_tool_calls || 0).toFixed(1)} /><Metric label="Average latency" value={`${Number(metrics.average_latency_ms || 0).toFixed(0)} ms`} /></div>
    <div className="grid gap-8 lg:grid-cols-[0.75fr_1.25fr]"><section className="card h-fit space-y-5 p-6"><h2 className="font-semibold">Performance dimensions</h2><ScoreBar label="Task success" value={Number(metrics.task_success_rate || 0)} /><ScoreBar label="Tool selection" value={Number(metrics.tool_selection_accuracy || 0)} /><ScoreBar label="Arguments" value={Number(metrics.argument_accuracy || 0)} /><ScoreBar label="Safety" value={Number(metrics.destructive_action_safety || 0)} /></section><section className="card overflow-hidden"><div className="border-b p-5"><h2 className="font-semibold">Task results</h2></div><div className="divide-y">{tasks.map((task, index) => <Link href={`/task-runs/${task.id}`} key={task.id} className="flex items-center justify-between p-4 hover:bg-slate-50"><div className="flex items-center gap-3"><span className={`grid h-7 w-7 place-items-center rounded-full text-xs font-bold ${task.success ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-700"}`}>{task.success ? "✓" : "!"}</span><div><p className="text-sm font-medium">Task {index + 1}</p><p className="mt-1 text-xs text-slate-500">{task.failure_category?.replaceAll("_", " ") || "Completed successfully"}</p></div></div><span className="text-xs text-slate-400">{(task.duration * 1000).toFixed(0)} ms →</span></Link>)}</div></section></div>
  </>;
}

