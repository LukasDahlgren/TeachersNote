const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";
const TOKEN_STORAGE_KEY = "teachers-note.access-token";

export function getBaseUrl(): string {
  return BASE;
}

export function getStoredToken(): string | null {
  return typeof window !== "undefined" ? window.localStorage.getItem(TOKEN_STORAGE_KEY) : null;
}

export function setStoredToken(token: string): void {
  window.localStorage.setItem(TOKEN_STORAGE_KEY, token);
}

export function clearStoredToken(): void {
  window.localStorage.removeItem(TOKEN_STORAGE_KEY);
}

function withAuthHeaders(headers?: HeadersInit): Headers {
  const next = new Headers(headers);
  const token = getStoredToken();
  if (token) next.set("Authorization", `Bearer ${token}`);
  return next;
}

export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  return fetch(`${BASE}${path}`, {
    ...init,
    headers: withAuthHeaders(init.headers),
  });
}

export function buildAssetUrl(path?: string | null): string | undefined {
  if (!path) return undefined;

  const target = path.startsWith("http://") || path.startsWith("https://")
    ? path
    : `${BASE}${path}`;
  const token = getStoredToken();
  if (!token) return target;

  try {
    const url = new URL(target, BASE);
    url.searchParams.set("token", token);
    return url.toString();
  } catch {
    return target;
  }
}

export class ApiError extends Error {
  status: number;
  data: unknown;

  constructor(status: number, message: string, data: unknown) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

export async function readBody(res: Response): Promise<unknown> {
  const contentType = res.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    try {
      return await res.json();
    } catch {
      return null;
    }
  }
  try {
    return await res.text();
  } catch {
    return null;
  }
}

export function parseEventPayload<T>(evt: Event): T | null {
  try {
    const message = evt as MessageEvent<string>;
    return JSON.parse(message.data) as T;
  } catch {
    return null;
  }
}
