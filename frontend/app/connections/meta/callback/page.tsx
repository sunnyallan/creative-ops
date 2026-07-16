"use client";
import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { apiFetch } from "@/lib/api";

// Force runtime rendering — this route is only ever hit as an OAuth redirect
// with fresh ?code=&state= params, so prerendering it is pointless.
export const dynamic = "force-dynamic";

function CallbackInner() {
  const router = useRouter();
  const params = useSearchParams();
  const [state, setState] = useState<"working" | "ok" | "err">("working");
  const [msg, setMsg] = useState<string>("Finalising Meta connection…");

  useEffect(() => {
    const code = params.get("code");
    const s = params.get("state");
    if (!code || !s) { setState("err"); setMsg("Missing code/state — restart the connect flow."); return; }
    const qs = new URLSearchParams({ code, state: s });
    apiFetch(`/connections/meta/callback?${qs}`)
      .then(() => {
        setState("ok");
        setMsg("Connected. Redirecting to your connections…");
        setTimeout(() => router.push("/settings/connections"), 1000);
      })
      .catch((e) => { setState("err"); setMsg(e.message); });
  }, [params, router]);

  return (
    <div className="mx-auto max-w-md px-6 py-16 text-center">
      <div className={`chip ${state === "ok" ? "chip-success" : state === "err" ? "chip-danger" : "chip-info"} mx-auto`}>
        {state === "working" ? "connecting…" : state === "ok" ? "success" : "failed"}
      </div>
      <p className="mt-4 text-fg">{msg}</p>
      {state === "err" && (
        <button onClick={() => router.push("/settings/connections")} className="btn btn-primary mt-4">
          Back to connections
        </button>
      )}
    </div>
  );
}

export default function MetaCallback() {
  return (
    <Suspense fallback={<div className="p-8 text-muted">Loading…</div>}>
      <CallbackInner />
    </Suspense>
  );
}
