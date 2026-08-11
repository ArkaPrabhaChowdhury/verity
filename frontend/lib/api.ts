import type { Run, RunEvent, Telemetry } from "./types";

export const API_URL = "/api/verity";

function requestHeaders(json = false): HeadersInit {
  return {
    ...(json ? { "Content-Type": "application/json" } : {}),
  };
}

export function streamURL(id: string) {
  return `${API_URL}/api/runs/${id}/stream`;
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { error?: string } | null;
    throw new Error(body?.error ?? `Request failed with HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function createRun(question: string, replanEnabled = true): Promise<string> {
  const response = await fetch(`${API_URL}/api/runs`, {
    method: "POST",
    headers: requestHeaders(true),
    body: JSON.stringify({ question, replan_enabled: replanEnabled }),
  });
  const data = await parseResponse<{ run_id: string }>(response);
  return data.run_id;
}

export async function getRun(id: string): Promise<Run> {
  return parseResponse<Run>(await fetch(`${API_URL}/api/runs/${id}`, { cache: "no-store", headers: requestHeaders() }));
}

export async function listRuns(): Promise<Run[]> {
  const data = await parseResponse<{ runs: Run[] }>(await fetch(`${API_URL}/api/runs?limit=50`, { cache: "no-store", headers: requestHeaders() }));
  return data.runs;
}

export async function getTelemetry(): Promise<Telemetry> {
  return parseResponse<Telemetry>(await fetch(`${API_URL}/api/telemetry`, { cache: "no-store", headers: requestHeaders() }));
}

export async function listRunEvents(id: string): Promise<RunEvent[]> {
  const data = await parseResponse<{ events: RunEvent[] }>(await fetch(`${API_URL}/api/runs/${id}/events`, { cache: "no-store", headers: requestHeaders() }));
  return data.events;
}

export async function cancelRun(id: string): Promise<void> {
  await parseResponse(await fetch(`${API_URL}/api/runs/${id}/cancel`, { method: "POST", headers: requestHeaders() }));
}

export async function retryRun(id: string): Promise<string> {
  const data = await parseResponse<{ run_id: string }>(await fetch(`${API_URL}/api/runs/${id}/retry`, { method: "POST", headers: requestHeaders() }));
  return data.run_id;
}

export async function deleteRun(id: string): Promise<void> {
  const response = await fetch(`${API_URL}/api/runs/${id}`, { method: "DELETE", headers: requestHeaders() });
  if (!response.ok) await parseResponse(response);
}
