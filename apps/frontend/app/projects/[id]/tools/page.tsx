"use client";

import {useParams} from "next/navigation";
import {useEffect, useState} from "react";
import {PageTitle, ProjectNav} from "@/components/ui";
import {getJSON, sendJSON, type Tool} from "@/lib/api";

export default function ToolsPage() {
  const id = useParams<{id: string}>().id; const [tools, setTools] = useState<Tool[]>([]); const [selected, setSelected] = useState<Tool>();
  useEffect(() => {getJSON<Tool[]>(`/api/projects/${id}/tools`).then(value => {setTools(value); setSelected(value[0]);});}, [id]);
  async function toggle(tool: Tool) {const updated = await sendJSON<Tool>(`/api/tools/${tool.id}?is_destructive=${!tool.is_destructive}`, "PATCH"); setTools(list => list.map(item => item.id === tool.id ? updated : item)); setSelected(updated);}
  return <><ProjectNav id={id} /><PageTitle eyebrow="Normalized interface" title="API explorer" description={`${tools.length} OpenAPI operations mapped into provider-independent tool definitions.`} />
    <div className="grid min-h-[560px] gap-6 lg:grid-cols-[0.9fr_1.5fr]"><section className="card overflow-hidden"><div className="border-b px-5 py-3 text-xs font-semibold uppercase tracking-wider text-slate-500">Discovered tools</div><div className="max-h-[620px] divide-y overflow-y-auto">{tools.map(tool => <button key={tool.id} onClick={() => setSelected(tool)} className={`w-full p-4 text-left hover:bg-slate-50 ${selected?.id === tool.id ? "bg-indigo-50" : ""}`}><div className="flex items-center gap-2"><span className={`rounded px-2 py-0.5 text-[10px] font-bold ${tool.http_method === "GET" ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700"}`}>{tool.http_method}</span><span className="font-mono text-sm font-semibold">{tool.name}</span>{tool.is_destructive && <span title="Destructive" className="text-red-500">◆</span>}</div><p className="mt-2 truncate text-xs text-slate-500">{tool.path}</p></button>)}</div></section>
      <section className="card p-7">{selected ? <><div className="mb-6 flex items-start justify-between"><div><p className="font-mono text-xl font-bold">{selected.name}</p><p className="mt-2 font-mono text-sm text-slate-500">{selected.http_method} {selected.path}</p></div><button onClick={() => toggle(selected)} className={selected.is_destructive ? "btn border border-red-200 bg-red-50 text-red-700" : "btn-secondary"}>{selected.is_destructive ? "Destructive" : "Mark destructive"}</button></div><p className="mb-6 text-slate-600">{selected.description || "No description supplied by the interface."}</p><dl className="grid grid-cols-2 gap-4 text-sm"><div className="rounded-xl bg-slate-50 p-4"><dt className="text-slate-500">Authentication</dt><dd className="mt-1 font-semibold">{selected.requires_authentication ? "Required" : "Not declared"}</dd></div><div className="rounded-xl bg-slate-50 p-4"><dt className="text-slate-500">Inference</dt><dd className="mt-1 font-semibold">{selected.inferred_destructive ? "Potentially destructive" : "Read / low risk"}</dd></div></dl><h3 className="mb-3 mt-7 font-semibold">Parameters</h3><pre className="max-h-72 overflow-auto rounded-xl bg-slate-950 p-5 text-xs text-slate-200">{JSON.stringify(selected.parameters, null, 2)}</pre></> : <p className="text-slate-500">Select a tool.</p>}</section></div>
  </>;
}

