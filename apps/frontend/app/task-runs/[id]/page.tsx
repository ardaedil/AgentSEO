"use client";

import Link from "next/link";
import {useParams} from "next/navigation";
import {useEffect, useState} from "react";
import {Metric, PageTitle, TraceTimeline} from "@/components/ui";
import {getJSON, type TaskRun} from "@/lib/api";

export default function TaskRunPage() {
  const id = useParams<{id: string}>().id; const [task, setTask] = useState<TaskRun>();
  useEffect(() => {getJSON<TaskRun>(`/api/task-runs/${id}`).then(setTask);}, [id]);
  return <><PageTitle eyebrow="Trace viewer" title={task?.success ? "Task completed" : task?.failure_category?.replaceAll("_", " ") || "Loading task…"} description={task?.failure_explanation || "Inspect the normalized model/tool trajectory and deterministic evaluator result."} action={task && <Link href={`/runs/${task.benchmark_run_id}`} className="btn-secondary">Back to run</Link>} />
    {task && <><div className="mb-8 grid gap-4 md:grid-cols-4"><Metric label="Outcome" value={task.success ? "Passed" : "Failed"} /><Metric label="Latency" value={`${(task.duration * 1000).toFixed(0)} ms`} /><Metric label="Tool calls" value={task.trace_events.filter(x => x.event_type === "TOOL_CALLED").length} /><Metric label="Estimated cost" value={`$${task.cost_estimate.toFixed(5)}`} /></div><div className="grid gap-8 lg:grid-cols-[1.25fr_0.75fr]"><section><h2 className="mb-5 font-semibold">Execution timeline</h2><TraceTimeline events={task.trace_events} /></section><aside className="card h-fit p-6"><h2 className="mb-4 font-semibold">Evaluator result</h2><pre className="max-h-[560px] overflow-auto whitespace-pre-wrap rounded-xl bg-slate-950 p-4 text-xs text-slate-200">{JSON.stringify(task.evaluator_result, null, 2)}</pre><p className="mt-4 text-xs leading-5 text-slate-500">AgentSEO does not store or display hidden chain-of-thought. This trace includes only provider-visible output and structured events.</p></aside></div></>}
  </>;
}

