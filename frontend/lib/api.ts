"use client";
import { supabaseBrowser } from "./supabase";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const sb = supabaseBrowser();
  const { data: { session } } = await sb.auth.getSession();
  const token = session?.access_token;
  const res = await fetch(`${API}${path}`, {
    ...init,
    headers: {
      "content-type": "application/json",
      ...(token ? { authorization: `Bearer ${token}` } : {}),
      ...(init.headers || {}),
    },
  });
  if (res.status === 403 && typeof window !== "undefined") {
    // Access control: the token is valid but the user isn't allowlisted.
    // Sign them out so they can't sit in a half-broken UI, and redirect.
    try { await sb.auth.signOut(); } catch {}
    window.location.href = "/login?forbidden=1";
    throw new Error("forbidden");
  }
  if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
  return res.json() as Promise<T>;
}
