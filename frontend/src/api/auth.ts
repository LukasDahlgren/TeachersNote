import type { AuthResponse, AuthUser } from "../types";
import { ApiError, apiFetch, clearStoredToken, getBaseUrl, readBody, setStoredToken } from "./client";

export async function login(email: string, password: string): Promise<AuthResponse> {
  const res = await fetch(`${getBaseUrl()}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    const body = await readBody(res);
    const message = (body as { detail?: string } | null)?.detail || `Login failed (${res.status})`;
    throw new ApiError(res.status, message, body);
  }
  const data: AuthResponse = await res.json();
  setStoredToken(data.access_token);
  return data;
}

export async function register(email: string, password: string, displayName?: string): Promise<AuthResponse> {
  const res = await fetch(`${getBaseUrl()}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, display_name: displayName }),
  });
  if (!res.ok) {
    const body = await readBody(res);
    const message = (body as { detail?: string } | null)?.detail || `Registration failed (${res.status})`;
    throw new ApiError(res.status, message, body);
  }
  const data: AuthResponse = await res.json();
  setStoredToken(data.access_token);
  return data;
}

export async function getMe(): Promise<AuthUser> {
  const res = await apiFetch("/auth/me");
  if (!res.ok) throw new ApiError(res.status, "Not authenticated", null);
  return res.json();
}

export function logout(): void {
  clearStoredToken();
}
