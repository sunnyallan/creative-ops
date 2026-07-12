"use client";
import { useEffect, useRef, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { apiFetch } from "@/lib/api";

type EditData = {
  id: string;
  dimensions: string;
  background_url: string | null;
  fallback_url: string | null;
  headline: string | null;
  body: string | null;
  cta: string | null;
  brand_colour: string | null;
  edit_layout: { layers?: Layer[] } | null;
  editable: boolean;
};

type Layer = {
  key: "headline" | "body" | "cta";
  text: string;
  xFrac: number;      // top-left x as fraction of canvas width
  yFrac: number;      // top-left y as fraction of canvas height
  fontPx: number;     // font size at FULL resolution
  color: string;
  weight: number;     // 400 | 700
  align: "left" | "center";
  pill: boolean;      // CTA renders as a pill
  pillColor: string;
};

const FONT = "'Geist', Inter, system-ui, -apple-system, sans-serif";

function parseDims(s: string): [number, number] {
  const [w, h] = s.toLowerCase().split("x").map(Number);
  return [w || 1080, h || 1080];
}

function defaultLayers(d: EditData, W: number, H: number): Layer[] {
  const brand = d.brand_colour && d.brand_colour.startsWith("#") ? d.brand_colour : "#111111";
  const layers: Layer[] = [];
  const pad = 0.05;
  let y = 0.66;
  if (d.headline) {
    layers.push({ key: "headline", text: d.headline, xFrac: pad, yFrac: y, fontPx: Math.round(H / 16), color: "#ffffff", weight: 700, align: "left", pill: false, pillColor: brand });
    y += 0.10;
  }
  if (d.body) {
    layers.push({ key: "body", text: d.body, xFrac: pad, yFrac: y, fontPx: Math.round(H / 34), color: "#ffffff", weight: 400, align: "left", pill: false, pillColor: brand });
    y += 0.07;
  }
  if (d.cta) {
    layers.push({ key: "cta", text: d.cta, xFrac: pad, yFrac: y + 0.02, fontPx: Math.round(H / 24), color: "#ffffff", weight: 700, align: "left", pill: true, pillColor: brand });
  }
  return layers;
}

export default function CreativeEditor() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [data, setData] = useState<EditData | null>(null);
  const [layers, setLayers] = useState<Layer[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [bgLoaded, setBgLoaded] = useState(false);
  const [editingKey, setEditingKey] = useState<string | null>(null);  // which layer is in text-edit mode

  const stageRef = useRef<HTMLDivElement>(null);
  const bgImgRef = useRef<HTMLImageElement | null>(null);
  const drag = useRef<{ key: string; startX: number; startY: number; ox: number; oy: number; moved: boolean } | null>(null);

  const [W, H] = data ? parseDims(data.dimensions) : [1080, 1080];
  const DISPLAY_W = 560;
  const scale = DISPLAY_W / W;
  const DISPLAY_H = H * scale;

  useEffect(() => {
    apiFetch<EditData>(`/creatives/${id}/edit-data`)
      .then((d) => {
        setData(d);
        const [w, h] = parseDims(d.dimensions);
        setLayers(d.edit_layout?.layers?.length ? d.edit_layout.layers : defaultLayers(d, w, h));
      })
      .catch((e) => setErr(e.message));
  }, [id]);

  // Preload background for canvas export
  useEffect(() => {
    const url = data?.background_url || data?.fallback_url;
    if (!url) return;
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => { bgImgRef.current = img; setBgLoaded(true); };
    img.src = url;
  }, [data]);

  const onPointerDown = (e: React.PointerEvent, key: string) => {
    if (editingKey === key) return; // in text-edit mode — let the caret work
    e.preventDefault();
    const l = layers.find((x) => x.key === key)!;
    drag.current = { key, startX: e.clientX, startY: e.clientY, ox: l.xFrac, oy: l.yFrac, moved: false };
    setSelected(key);
    // Capture on the layer element itself so move/up fire here even if the
    // pointer leaves the element during a fast drag.
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  };
  const onLayerPointerMove = (e: React.PointerEvent) => {
    if (!drag.current) return;
    const dx = (e.clientX - drag.current.startX) / DISPLAY_W;
    const dy = (e.clientY - drag.current.startY) / DISPLAY_H;
    if (Math.abs(dx) > 0.002 || Math.abs(dy) > 0.002) drag.current.moved = true;
    const k = drag.current.key;
    setLayers((ls) => ls.map((l) => l.key === k
      ? { ...l, xFrac: Math.max(0, Math.min(0.95, drag.current!.ox + dx)), yFrac: Math.max(0, Math.min(0.95, drag.current!.oy + dy)) }
      : l));
  };
  const onLayerPointerUp = (e: React.PointerEvent, key: string) => {
    const wasDrag = drag.current?.moved;
    drag.current = null;
    try { (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId); } catch {}
    // A tap that didn't move just selects; the double-click handler enters edit mode.
    if (!wasDrag) setSelected(key);
  };

  function updateLayer(key: string, patch: Partial<Layer>) {
    setLayers((ls) => ls.map((l) => (l.key === key ? { ...l, ...patch } : l)));
  }

  const renderToCanvas = useCallback((): string | null => {
    const bg = bgImgRef.current;
    const canvas = document.createElement("canvas");
    canvas.width = W; canvas.height = H;
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;
    if (bg) ctx.drawImage(bg, 0, 0, W, H);
    else { ctx.fillStyle = "#111"; ctx.fillRect(0, 0, W, H); }

    for (const l of layers) {
      if (!l.text.trim()) continue;
      ctx.font = `${l.weight} ${l.fontPx}px ${FONT}`;
      ctx.textBaseline = "top";
      const x = l.xFrac * W;
      const y = l.yFrac * H;
      if (l.pill) {
        const m = ctx.measureText(l.text);
        const padX = l.fontPx * 0.9, padY = l.fontPx * 0.45;
        const pw = m.width + padX * 2, ph = l.fontPx + padY * 2;
        const r = ph / 2;
        ctx.fillStyle = l.pillColor;
        ctx.beginPath();
        ctx.roundRect(x, y, pw, ph, r);
        ctx.fill();
        ctx.fillStyle = l.color;
        ctx.fillText(l.text, x + padX, y + padY);
      } else {
        // simple shadow for legibility
        ctx.fillStyle = "rgba(0,0,0,0.4)";
        ctx.fillText(l.text, x + 2, y + 2);
        ctx.fillStyle = l.color;
        ctx.fillText(l.text, x, y);
      }
    }
    return canvas.toDataURL("image/webp", 0.85);
  }, [layers, W, H]);

  async function save() {
    setSaving(true); setErr(null);
    try {
      const dataUrl = renderToCanvas();
      if (!dataUrl) throw new Error("could not render canvas");
      await apiFetch(`/creatives/${id}/edit`, {
        method: "POST",
        body: JSON.stringify({ image_data_url: dataUrl, edit_layout: { layers } }),
      });
      router.push("/review");
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setSaving(false);
    }
  }

  if (err && !data) return <main className="p-12 text-red-600">{err}</main>;
  if (!data) return <main className="p-12">Loading…</main>;

  if (!data.editable) {
    return (
      <main className="mx-auto max-w-xl px-6 py-12">
        <Link href="/review" className="text-sm text-blue-600">← Review</Link>
        <h1 className="mt-2 text-2xl font-semibold">Editing not available</h1>
        <p className="mt-3 text-neutral-600">
          This creative was generated before the editor existed (no text-free background was saved).
          Regenerate the campaign to enable editing on new creatives.
        </p>
      </main>
    );
  }

  const sel = layers.find((l) => l.key === selected);

  return (
    <main className="mx-auto max-w-5xl px-6 py-8">
      <div className="flex items-center justify-between">
        <Link href="/review" className="text-sm text-blue-600">← Review</Link>
        <div className="flex gap-2">
          <button onClick={() => { const [w, h] = parseDims(data.dimensions); setLayers(defaultLayers(data, w, h)); }}
            className="rounded-md border px-3 py-1.5 text-sm">Reset</button>
          <button onClick={save} disabled={saving || !bgLoaded}
            className="rounded-md bg-neutral-900 px-4 py-1.5 text-sm text-white disabled:opacity-50">
            {saving ? "Saving…" : "Save changes"}
          </button>
        </div>
      </div>
      <h1 className="mt-2 text-2xl font-semibold">Edit creative</h1>
      <p className="text-sm text-neutral-600">
        <b>Drag</b> a text layer to move it · <b>double-click</b> to edit the words · restyle it in the panel.
      </p>

      <div className="mt-5 flex flex-col gap-6 lg:flex-row">
        {/* Stage */}
        <div
          ref={stageRef}
          className="relative shrink-0 select-none overflow-hidden rounded-lg border bg-neutral-100"
          style={{ width: DISPLAY_W, height: DISPLAY_H }}
          onPointerDown={(e) => { if (e.target === stageRef.current) { setSelected(null); setEditingKey(null); } }}
        >
          {(data.background_url || data.fallback_url) && (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={(data.background_url || data.fallback_url)!} alt="" draggable={false} className="pointer-events-none absolute inset-0 h-full w-full object-cover" />
          )}
          {layers.map((l) => {
            const isEditing = editingKey === l.key;
            return (
              <div
                key={l.key}
                onPointerDown={(e) => onPointerDown(e, l.key)}
                onPointerMove={onLayerPointerMove}
                onPointerUp={(e) => onLayerPointerUp(e, l.key)}
                onDoubleClick={() => { setEditingKey(l.key); setSelected(l.key); }}
                style={{
                  position: "absolute",
                  left: l.xFrac * DISPLAY_W,
                  top: l.yFrac * DISPLAY_H,
                  fontFamily: FONT,
                  fontWeight: l.weight,
                  fontSize: l.fontPx * scale,
                  color: l.color,
                  cursor: isEditing ? "text" : "move",
                  whiteSpace: "nowrap",
                  lineHeight: 1.1,
                  touchAction: "none",
                  textShadow: l.pill ? "none" : "0 1px 2px rgba(0,0,0,0.4)",
                  background: l.pill ? l.pillColor : "transparent",
                  padding: l.pill ? `${l.fontPx * scale * 0.45}px ${l.fontPx * scale * 0.9}px` : 0,
                  borderRadius: l.pill ? 999 : 0,
                  outline: selected === l.key ? (isEditing ? "2px solid #16a34a" : "2px solid #2563eb") : "none",
                  outlineOffset: 2,
                }}
              >
                <span
                  contentEditable={isEditing}
                  suppressContentEditableWarning
                  onBlur={(e) => { updateLayer(l.key, { text: e.currentTarget.textContent || "" }); setEditingKey(null); }}
                  onPointerDown={(e) => { if (isEditing) e.stopPropagation(); }}
                  className="outline-none"
                >
                  {l.text}
                </span>
              </div>
            );
          })}
        </div>
        {editingKey === null && selected && (
          <p className="mt-1 text-xs text-neutral-500 lg:hidden">Double-tap a layer to edit its text.</p>
        )}

        {/* Inspector */}
        <div className="flex-1 space-y-4">
          {sel ? (
            <>
              <h2 className="font-semibold capitalize">{sel.key}</h2>
              <label className="block text-sm">
                <div className="flex justify-between"><span>Size</span><span className="text-neutral-500">{sel.fontPx}px</span></div>
                <input type="range" min={16} max={Math.round(H / 6)} value={sel.fontPx}
                  onChange={(e) => updateLayer(sel.key, { fontPx: Number(e.target.value) })} className="w-full" />
              </label>
              <div className="flex items-center gap-3 text-sm">
                <span>Text colour</span>
                <input type="color" value={sel.color.startsWith("#") ? sel.color : "#ffffff"}
                  onChange={(e) => updateLayer(sel.key, { color: e.target.value })} className="h-8 w-12 rounded border" />
                <button onClick={() => updateLayer(sel.key, { color: "#ffffff" })} className="text-xs text-blue-600">white</button>
                <button onClick={() => updateLayer(sel.key, { color: "#111111" })} className="text-xs text-blue-600">black</button>
              </div>
              <div className="flex items-center gap-3 text-sm">
                <span>Weight</span>
                <button onClick={() => updateLayer(sel.key, { weight: 400 })}
                  className={`rounded border px-2 py-1 text-xs ${sel.weight === 400 ? "bg-neutral-900 text-white" : ""}`}>Regular</button>
                <button onClick={() => updateLayer(sel.key, { weight: 700 })}
                  className={`rounded border px-2 py-1 text-xs ${sel.weight === 700 ? "bg-neutral-900 text-white" : ""}`}>Bold</button>
              </div>
              {sel.key === "cta" && (
                <div className="flex items-center gap-3 text-sm">
                  <label className="flex items-center gap-2">
                    <input type="checkbox" checked={sel.pill} onChange={(e) => updateLayer(sel.key, { pill: e.target.checked })} />
                    Pill background
                  </label>
                  {sel.pill && (
                    <input type="color" value={sel.pillColor.startsWith("#") ? sel.pillColor : "#111111"}
                      onChange={(e) => updateLayer(sel.key, { pillColor: e.target.value })} className="h-8 w-12 rounded border" />
                  )}
                </div>
              )}
            </>
          ) : (
            <p className="text-sm text-neutral-500">Select a text layer on the left to restyle it.</p>
          )}

          <div className="rounded-md bg-neutral-50 p-3 text-xs text-neutral-600">
            Editing text over a text-free version of the image. Your saved changes replace the creative in the review queue.
          </div>
          {err && <p className="text-sm text-red-600">{err}</p>}
        </div>
      </div>
    </main>
  );
}
