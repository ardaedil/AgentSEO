export const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type Project = {id: string; name: string; description: string; sandbox_domain: string; created_at: string; updated_at: string};
export type Tool = {id: string; name: string; operation_id: string; http_method: string; path: string; description: string; parameters: Array<Record<string, unknown>>; tags: string[]; is_destructive: boolean; inferred_destructive: boolean; requires_authentication: boolean};
export type Task = {id: string; project_id: string; title: string; natural_language_instruction: string; difficulty: number; category: string; required_tools: string[]; forbidden_tools: string[]; requires_clarification: boolean; safety_level: string; enabled: boolean; version: number; initial_state: Record<string, unknown>; expected_final_state: Array<Record<string, unknown>>; expected_invariants: Array<Record<string, unknown>>; generated_or_manual: string};
export type Run = {id: string; project_id: string; model: string; provider: string; status: string; started_at: string; completed_at: string; aggregate_metrics: Record<string, number | boolean | Record<string, number>>; synthetic: boolean};
export type Trace = {id: string; event_type: string; sequence: number; timestamp: string; payload: Record<string, unknown>};
export type TaskRun = {id: string; task_id: string; benchmark_run_id: string; status: string; success: boolean; duration: number; token_usage: Record<string, number>; cost_estimate: number; failure_category: string | null; failure_explanation: string | null; evaluator_result: Record<string, unknown>; trace_events: Trace[]};

export async function getJSON<T>(path: string): Promise<T> {
  const response = await fetch(`${API}${path}`, {cache: "no-store"});
  if (!response.ok) throw new Error(await response.text());
  return response.json() as Promise<T>;
}

export async function sendJSON<T>(path: string, method: string, body?: unknown): Promise<T> {
  const response = await fetch(`${API}${path}`, {method, headers: body === undefined ? undefined : {"Content-Type": "application/json"}, body: body === undefined ? undefined : JSON.stringify(body)});
  if (!response.ok) throw new Error(await response.text());
  return response.status === 204 ? (undefined as T) : response.json() as Promise<T>;
}

