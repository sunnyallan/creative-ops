"use client";
import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

type Connection = {
  id: string;
  provider: string;
  meta_user_id: string;
  meta_user_name: string | null;
  status: "connected" | "disconnected" | "error";
  selected_ad_account_id: string | null;
  selected_page_id: string | null;
  selected_page_name: string | null;
  selected_ig_user_id: string | null;
  selected_ig_username: string | null;
  token_expires_at: string | null;
  last_verified_at: string | null;
  last_error: string | null;
};

type Page = { id: string; name: string; page_access_token?: string; ig?: { id: string; username: string } | null };
type AdAccount = { id: string; name: string; currency?: string; account_status?: number };

export default function ConnectionsPage() {
  const [conns, setConns] = useState<Connection[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [picker, setPicker] = useState<{ connectionId: string; adAccounts: AdAccount[]; pages: Page[] } | null>(null);

  async function load() {
    try { setConns(await apiFetch<Connection[]>("/connections")); }
    catch (e: any) { setErr(e.message); }
  }
  useEffect(() => { load(); }, []);

  async function connect() {
    setBusy("connect"); setErr(null);
    try {
      const { url } = await apiFetch<{ url: string; state: string }>("/connections/meta/oauth-url");
      window.location.href = url;
    } catch (e: any) {
      setErr(e.message);
      setBusy(null);
    }
  }

  async function refresh(c: Connection) {
    setBusy(c.id); setErr(null);
    try {
      const r = await apiFetch<{ ad_accounts: AdAccount[]; pages: Page[] }>(`/connections/${c.id}/refresh`, { method: "POST" });
      setPicker({ connectionId: c.id, adAccounts: r.ad_accounts || [], pages: r.pages || [] });
      load();
    } catch (e: any) { setErr(e.message); }
    finally { setBusy(null); }
  }

  async function disconnect(c: Connection) {
    if (!confirm(`Disconnect ${c.meta_user_name || c.meta_user_id}? Live experiments on this account will fail.`)) return;
    await apiFetch(`/connections/${c.id}`, { method: "DELETE" });
    load();
  }

  async function select(connectionId: string, adAccountId: string, page: Page) {
    await apiFetch("/connections/meta/select", {
      method: "POST",
      body: JSON.stringify({
        connection_id: connectionId,
        ad_account_id: adAccountId,
        page_id: page.id,
        page_name: page.name,
        page_access_token: page.page_access_token,
        ig_user_id: page.ig?.id,
        ig_username: page.ig?.username,
      }),
    });
    setPicker(null);
    load();
  }

  return (
    <div className="mx-auto max-w-4xl px-6 py-8">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-fg">Connections</h1>
          <p className="text-sm text-muted mt-0.5">
            Where the orchestrator publishes. Meta covers ads + Instagram + Facebook pages
            in one connection. Sandbox works today; live publishing waits on Meta App Review.
          </p>
        </div>
        <button onClick={connect} disabled={busy === "connect"} className="btn btn-primary text-sm">
          {busy === "connect" ? "…" : "+ Connect Meta"}
        </button>
      </div>

      {err && <div className="chip chip-danger mt-3">{err}</div>}

      <section className="mt-6 space-y-3">
        {conns.length === 0 ? (
          <div className="surface p-8 text-center">
            <div className="text-sm text-fg font-medium">No connections yet</div>
            <p className="text-xs text-muted mt-2 max-w-md mx-auto">
              Run experiments on <span className="chip">mock_ads</span> today without connecting anything.
              Connect Meta when you're ready to publish real ads or Instagram posts.
            </p>
          </div>
        ) : (
          conns.map((c) => (
            <article key={c.id} className="surface p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm text-fg font-medium">{c.meta_user_name || "Meta user"}</span>
                    <span className={`chip ${c.status === "connected" ? "chip-success" : c.status === "error" ? "chip-danger" : "chip-warn"}`}>
                      {c.status}
                    </span>
                    {c.selected_ig_username && <span className="chip">IG @{c.selected_ig_username}</span>}
                  </div>
                  <div className="text-xs text-muted mt-1">
                    Meta ID {c.meta_user_id}
                    {c.token_expires_at && <> · token expires {new Date(c.token_expires_at).toLocaleDateString()}</>}
                  </div>
                  {c.last_error && <div className="chip chip-danger mt-1 text-[10px]">{c.last_error}</div>}
                </div>
                <div className="flex flex-col gap-1 shrink-0">
                  <button onClick={() => refresh(c)} disabled={busy === c.id}
                    className="btn text-xs">
                    {busy === c.id ? "…" : "Refresh & pick"}
                  </button>
                  <button onClick={() => disconnect(c)} className="btn btn-danger text-xs">
                    Disconnect
                  </button>
                </div>
              </div>

              <div className="mt-3 grid grid-cols-1 md:grid-cols-3 gap-2 text-xs">
                <Slot label="Ad account" value={c.selected_ad_account_id} />
                <Slot label="Page" value={c.selected_page_name} />
                <Slot label="Instagram" value={c.selected_ig_username ? `@${c.selected_ig_username}` : null} />
              </div>
            </article>
          ))
        )}
      </section>

      {picker && (
        <PickerModal
          picker={picker}
          onSelect={(adId, page) => select(picker.connectionId, adId, page)}
          onClose={() => setPicker(null)}
        />
      )}

      <div className="mt-6 text-xs text-subtle">
        Meta App Review is a 2–6 week external process. Follow{" "}
        <code className="chip">docs/meta-approval-filings.md</code> in the repo for the day-1 filing checklist.
      </div>
    </div>
  );
}

function Slot({ label, value }: { label: string; value: string | null }) {
  return (
    <div className="surface-2 p-2">
      <div className="text-[10px] uppercase tracking-wider text-subtle">{label}</div>
      <div className="text-sm text-fg mt-0.5">{value || <span className="text-subtle">— not picked</span>}</div>
    </div>
  );
}

function PickerModal({ picker, onSelect, onClose }: {
  picker: { adAccounts: AdAccount[]; pages: Page[] };
  onSelect: (adId: string, page: Page) => void;
  onClose: () => void;
}) {
  const [ad, setAd] = useState<string>(picker.adAccounts[0]?.id || "");
  const [pageId, setPageId] = useState<string>(picker.pages[0]?.id || "");
  const page = picker.pages.find((p) => p.id === pageId);
  return (
    <div className="fixed inset-0 z-50 bg-black/50 grid place-items-center px-4">
      <div className="surface p-5 w-full max-w-lg">
        <div className="flex items-center justify-between">
          <h3 className="font-semibold text-fg">Pick ad account + page</h3>
          <button onClick={onClose} className="btn btn-ghost text-xs">✕</button>
        </div>
        <div className="mt-4 space-y-3">
          <div>
            <label className="field">Ad account</label>
            <select value={ad} onChange={(e) => setAd(e.target.value)} className="input">
              {picker.adAccounts.map((a) => (
                <option key={a.id} value={a.id}>{a.name} · {a.id} ({a.currency || "?"})</option>
              ))}
            </select>
          </div>
          <div>
            <label className="field">Facebook page (also grants IG when linked)</label>
            <select value={pageId} onChange={(e) => setPageId(e.target.value)} className="input">
              {picker.pages.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}{p.ig ? ` · IG @${p.ig.username}` : ""}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button onClick={onClose} className="btn text-sm">Cancel</button>
          <button
            onClick={() => page && onSelect(ad, page)}
            disabled={!ad || !page}
            className="btn btn-primary text-sm">
            Save selection
          </button>
        </div>
      </div>
    </div>
  );
}
