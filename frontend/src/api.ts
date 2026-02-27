import type { ProcessResult } from "./types";

const BASE = "http://localhost:8000";

export async function processFiles(pdf: File, audio: File): Promise<ProcessResult> {
  const form = new FormData();
  form.append("pdf", pdf);
  form.append("audio", audio);
  const res = await fetch(`${BASE}/process`, { method: "POST", body: form });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function checkHealth(): Promise<boolean> {
  try {
    const res = await fetch(`${BASE}/health`);
    return res.ok;
  } catch {
    return false;
  }
}
