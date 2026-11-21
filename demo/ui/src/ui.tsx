// Small shared pieces built on BoardUI: app context, record links, status chips, cards.
import { createContext, useContext, type ReactNode } from "react";
import { Chip, type ChipColor } from "@/components/base/badges/chip";
import { cx } from "@/utils/cx";
import type { Bucket, HumanDecision, SystemDecision } from "./api";

export interface Reviewer { name: string; role: "analyst" | "checker" | "qa" }

export const AppCtx = createContext<{ openRecord: (id: string) => void; reviewer: Reviewer | null; blind: boolean; toast: (t: string, d?: string, ok?: boolean) => void }>({
  openRecord: () => {}, reviewer: null, blind: false, toast: () => {},
});
export const useApp = () => useContext(AppCtx);

export const SYS: Record<SystemDecision, { label: string; color: ChipColor }> = {
  DIFFERENT_ENTITY: { label: "Clear", color: "lime" },
  SAME_ENTITY: { label: "Match", color: "rose" },
  REVIEW: { label: "Review", color: "yellow" },
};
export const HUM: Record<HumanDecision, { label: string; color: ChipColor }> = {
  CLEAR: { label: "Clear", color: "lime" }, CONFIRM: { label: "Match", color: "rose" }, ESCALATE: { label: "Escalate", color: "orange" },
};
export const BUCKET: Record<Bucket, { label: string; color: ChipColor }> = {
  needs_decision: { label: "Needs decision", color: "yellow" }, returned: { label: "Returned", color: "orange" },
  pending_approval: { label: "Awaiting approval", color: "purple" }, proposed_match: { label: "Proposed match", color: "rose" },
  proposed_clear: { label: "Proposed clear", color: "lime" }, escalated: { label: "Escalated", color: "orange" }, done: { label: "Closed", color: "gray" },
};

export const plain = (s?: string | null) => (s || "").toLowerCase().replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());

export function StatusChip({ color, children }: { color: ChipColor; children: ReactNode }) {
  return <Chip color={color} variant="subtle">{children}</Chip>;
}

/** A record ID; click to read the record. */
export function RecordLink({ id }: { id?: string | null }) {
  const { openRecord } = useApp();
  if (!id) return null;
  return (
    <button type="button" onClick={(e) => { e.stopPropagation(); openRecord(id); }}
      className="rounded-md border border-separator-border bg-background-secondary-default px-1.5 py-0.5 font-mono text-[11px] text-text-secondary hover:border-accent-400 hover:text-accent-600 focus-visible:outline-2 focus-visible:outline-accent-500">
      {id}
    </button>
  );
}

export function Card({ title, aside, children, className, pad = true }: { title?: ReactNode; aside?: ReactNode; children: ReactNode; className?: string; pad?: boolean }) {
  return (
    <section className={cx("rounded-xl border border-separator-border bg-background-primary-default", className)}>
      {(title || aside) && (
        <header className="flex items-center justify-between gap-3 border-b border-separator-border px-5 py-3">
          <h3 className="text-headline-semibold text-text-primary">{title}</h3>
          {aside}
        </header>
      )}
      <div className={pad ? "p-5" : ""}>{children}</div>
    </section>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="py-10 text-center text-body-regular text-text-tertiary">{children}</p>;
}
