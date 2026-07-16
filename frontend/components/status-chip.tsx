"use client";

export function StatusChip({ status }: { status: string }) {
  const map: Record<string, string> = {
    running: "chip-success",
    paused: "chip-warn",
    awaiting_approval: "chip-warn",
    goal_met: "chip-accent",
    budget_exhausted: "chip-info",
    stopped: "chip",
    failed: "chip-danger",
    draft: "chip",
  };
  return <span className={`chip ${map[status] || "chip"}`}>{status.replace(/_/g, " ")}</span>;
}
