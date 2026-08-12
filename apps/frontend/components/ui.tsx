import Link from "next/link";
import type {Trace} from "@/lib/api";

export function PageTitle({eyebrow, title, description, action}: {eyebrow: string; title: string; description?: string; action?: React.ReactNode}) {
  return <div className="mb-8 flex items-end justify-between gap-6"><div><p className="eyebrow mb-2">{eyebrow}</p><h1 className="text-3xl font-bold tracking-tight">{title}</h1>{description && <p className="mt-2 max-w-3xl text-slate-600">{description}</p>}</div>{action}</div>;
}

export function ProjectNav({id}: {id: string}) {
  const links = [["Overview", `/projects/${id}`], ["API explorer", `/projects/${id}/tools`], ["Task suite", `/projects/${id}/tasks`], ["New benchmark", `/projects/${id}/benchmark`], ["Report", `/projects/${id}/report`]];
  return <nav className="mb-8 flex gap-1 rounded-xl border border-slate-200 bg-white p-1">{links.map(([label, href]) => <Link key={href} href={href} className="rounded-lg px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 hover:text-ink">{label}</Link>)}</nav>;
}

export function Metric({label, value, note}: {label: string; value: string | number; note?: string}) {
  return <div className="card p-5"><p className="text-sm text-slate-500">{label}</p><p className="mt-2 text-3xl font-bold">{value}</p>{note && <p className="mt-1 text-xs text-slate-500">{note}</p>}</div>;
}

export function ScoreBar({label, value}: {label: string; value: number}) {
  const percent = value <= 1 ? value * 100 : value;
  return <div><div className="mb-1.5 flex justify-between text-sm"><span className="text-slate-600">{label}</span><span className="font-semibold">{percent.toFixed(0)}%</span></div><div className="h-2.5 rounded-full bg-slate-100"><div className="h-full rounded-full bg-accent" style={{width: `${Math.max(0, Math.min(100, percent))}%`}} /></div></div>;
}

export function TraceTimeline({events}: {events: Trace[]}) {
  const colors: Record<string, string> = {ERROR: "bg-red-500", TOOL_CALLED: "bg-accent", TOOL_RESULT: "bg-mint", CLARIFICATION: "bg-amber-500", FINAL_RESPONSE: "bg-slate-700"};
  return <ol className="relative ml-3 border-l border-slate-200">{events.map(event => <li key={event.id} className="mb-6 ml-7"><span className={`absolute -left-2 mt-1 h-4 w-4 rounded-full border-4 border-white ${colors[event.event_type] || "bg-slate-400"}`} /><div className="card p-4"><div className="mb-2 flex items-center justify-between"><span className="text-xs font-bold tracking-wider text-slate-500">{event.event_type.replaceAll("_", " ")}</span><time className="text-xs text-slate-400">#{event.sequence}</time></div><pre className="overflow-auto whitespace-pre-wrap text-sm text-slate-700">{JSON.stringify(event.payload, null, 2)}</pre></div></li>)}</ol>;
}

