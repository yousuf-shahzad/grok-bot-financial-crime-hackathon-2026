import { useEffect, useState } from "react";
import { RiInboxLine, RiUserFollowLine, RiFlaskLine, RiCheckboxCircleLine, RiArrowRightLine } from "@remixicon/react";
import { StatCards } from "@/components/application/dashboard/stat-cards";
import { Button } from "@/components/base/buttons/button";
import { api, type Mi, type Summary } from "./api";
import type { Reviewer } from "./ui";
import type { QueueKey } from "./App";

export default function Overview({ summary, counts, tick, onOpen, reviewer }: {
  summary: Summary; counts: Record<QueueKey, number>; tick: number; onOpen: (k: QueueKey) => void; reviewer: Reviewer | null;
}) {
  const [mi, setMi] = useState<Mi | null>(null);
  useEffect(() => { api.mi().then(setMi).catch(() => {}); }, [tick]);
  const n = (d: string) => Object.values(summary.by_decision[d] || {}).reduce((a, b) => a + b, 0);
  const pct = (x: number) => `${Math.round((100 * x) / Math.max(1, summary.hits))}%`;
  const grok = !summary.llm.startsWith("rules");

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-8 px-8 py-10">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-body-2-medium text-text-tertiary">{summary.hits} watchlist hits across {summary.alerts} alerts</p>
          <h1 className="mt-1 text-large-title-semibold text-text-primary">{reviewer ? `Hi ${reviewer.name.split(" ")[0]}` : "Tryll"}</h1>
          <p className="mt-2 max-w-xl text-body-regular text-text-secondary">Tryll checks every hit against the bank's rules and only clears the ones it can prove are someone else. You make the final call on the rest.</p>
        </div>
        <Button variant="primary" trailingIcon={RiArrowRightLine} onClick={() => onOpen("decide")}>Review {counts.decide} cases</Button>
      </div>

      <StatCards variant="footer" columns={4} stats={[
        { icon: RiInboxLine, label: "To decide", value: String(counts.decide), delta: "", deltaColor: "neutral", tone: "orange", caption: "Need a person" },
        { icon: RiUserFollowLine, label: "To approve", value: String(counts.approve), delta: "", deltaColor: "neutral", tone: "purple", caption: "Second signature" },
        { icon: RiFlaskLine, label: "QA sample", value: String(counts.qa), delta: "", deltaColor: "neutral", tone: "sky", caption: "Spot-check clears" },
        { icon: RiCheckboxCircleLine, label: "Closed", value: String(counts.closed), delta: pct(counts.closed), deltaColor: "lime", tone: "emerald", caption: "Of all hits" },
      ]} />

      <div className="grid gap-5 lg:grid-cols-2">
        <section className="rounded-2xl border border-separator-border bg-background-primary-default p-6">
          <h2 className="text-headline-semibold text-text-primary">What Tryll found</h2>
          <div className="mt-5 flex h-2.5 overflow-hidden rounded-full bg-background-secondary-default">
            <div className="bg-lime-500" style={{ width: pct(n("DIFFERENT_ENTITY")) }} />
            <div className="bg-amber-400" style={{ width: pct(n("REVIEW")) }} />
            <div className="bg-rose-500" style={{ width: pct(n("SAME_ENTITY")) }} />
          </div>
          <div className="mt-5 grid grid-cols-3 gap-4">
            {[["Cleared", n("DIFFERENT_ENTITY"), "bg-lime-500"], ["For a person", n("REVIEW"), "bg-amber-400"], ["Likely match", n("SAME_ENTITY"), "bg-rose-500"]].map(([l, v, c]) => (
              <div key={String(l)}><p className="flex items-center gap-1.5 text-caption-1-medium text-text-tertiary"><span className={`size-2 rounded-full ${c}`} />{l}</p><p className="mt-1 text-title-2-semibold text-text-primary">{v}</p></div>
            ))}
          </div>
          {summary.practice.n > 0 && <p className="mt-5 border-t border-separator-border pt-4 text-body-2-regular text-text-secondary">Practice set: <b className="text-text-primary">{summary.practice.score}%</b> score, <b className="text-text-primary">{summary.practice.unsafe}</b> unsafe clearances.</p>}
        </section>

        <section className="rounded-2xl border border-separator-border bg-background-primary-default p-6">
          <h2 className="text-headline-semibold text-text-primary">How a decision is made</h2>
          <ol className="mt-4 flex flex-col gap-4">
            {[
              ["Rules", "The bank's procedure, as code. Clears only on a proven contradiction."],
              ["Grok", grok ? "Gives its own view and re-reads every clearance. It can never clear a hit by itself." : "Off: no model key, so the rules decide alone."],
              ["You", "Decide with a reason and the records you rely on."],
              ["A colleague", "Approves or sends it back. The log cannot be changed."],
            ].map(([t, d], i) => (
              <li key={t} className="flex gap-3">
                <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-background-secondary-default text-caption-1-semibold text-text-secondary">{i + 1}</span>
                <span><span className="block text-body-semibold text-text-primary">{t}</span><span className="block text-body-2-regular text-text-secondary">{d}</span></span>
              </li>
            ))}
          </ol>
          {mi && mi.decisions > 0 && <p className="mt-5 border-t border-separator-border pt-4 text-body-2-regular text-text-secondary">{mi.decisions} decisions so far, {mi.approvals} approved, {mi.agreement_rate}% agreed with Tryll.</p>}
        </section>
      </div>
    </div>
  );
}
