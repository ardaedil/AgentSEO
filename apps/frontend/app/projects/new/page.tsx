"use client";

import {FormEvent, useState} from "react";
import {useRouter} from "next/navigation";
import {PageTitle} from "@/components/ui";
import {API, sendJSON, type Project} from "@/lib/api";

export default function NewProject() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setLoading(true); setError("");
    const form = new FormData(event.currentTarget);
    try {
      const project = await sendJSON<Project>("/api/projects", "POST", {name: form.get("name"), description: form.get("description"), sandbox_domain: form.get("sandbox_domain")});
      const upload = new FormData(); upload.append("file", form.get("spec") as File);
      const response = await fetch(`${API}/api/projects/${project.id}/specs`, {method: "POST", body: upload});
      if (!response.ok) throw new Error(await response.text());
      router.push(`/projects/${project.id}/tools`);
    } catch (error) {setError(String(error)); setLoading(false);}
  }
  return <div className="mx-auto max-w-3xl"><PageTitle eyebrow="New project" title="Import an OpenAPI interface" description="Specs are parsed only. AgentSEO never sends benchmark traffic to the uploaded server URLs." />
    <form onSubmit={submit} className="card space-y-6 p-7">
      <div><label className="label" htmlFor="name">Project name</label><input className="input" id="name" name="name" required placeholder="Acme Billing API" /></div>
      <div><label className="label" htmlFor="description">Description</label><textarea className="input min-h-24" id="description" name="description" placeholder="What this interface is used for" /></div>
      <div><label className="label" htmlFor="sandbox_domain">Sandbox dataset</label><select className="input" id="sandbox_domain" name="sandbox_domain" defaultValue="billing"><option value="billing">SaaS billing</option><option value="ecommerce">E-commerce</option><option value="crm">CRM</option><option value="generic">Generic (inspection only)</option></select></div>
      <div><label className="label" htmlFor="spec">OpenAPI 3.x JSON or YAML</label><input className="input file:mr-4 file:rounded-md file:border-0 file:bg-indigo-50 file:px-3 file:py-1 file:text-accent" type="file" id="spec" name="spec" accept=".yaml,.yml,.json,application/json,text/yaml" required /><p className="mt-2 text-xs text-slate-500">Maximum 2 MB. YAML is parsed in safe mode; external references and executable content are rejected.</p></div>
      {error && <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>}
      <button disabled={loading} className="btn-primary w-full">{loading ? "Importing interface…" : "Create project and inspect tools"}</button>
    </form>
  </div>;
}

