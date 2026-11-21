import { useEffect, useState } from "react";
import { RiInboxLine, RiUserFollowLine, RiFlaskLine, RiCheckboxCircleLine } from "@remixicon/react";
import { StatCards } from "@/components/application/dashboard/stat-cards";
import { Button } from "@/components/base/buttons/button";
import { api, type Mi, type Summary } from "./api";
import { Card } from "./ui";
import type { QueueKey } from "./App";

export default function Overview({ summary, counts, tick, onOpen }: { summary: Summary; counts: Record<QueueKey, number>; tick: number; onOpen: (k: QueueKey) => void }) {
  const [mi, setMi] = useState<Mi | null>(null);
  useEffect(() => { api.mi().then(setMi).catch(() => {}); }, [tick]);
  const n = (d: string) => Object.values(summary.by_decision[d] || {}).reduce((a, b) => a + b, 0);
  const pct = (x: number) => `${Math.round((100 * x) / Math.max(1, summary.hits))}%`;

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-8 p-10">
      <div>
        <h1 className="text-title-1-semibold text-text-primary">Good to see you</h1>
        <p className="mt-1 max-w-2xl text-body-regular text-text-secondary">
          The engine recommends. You decide, a second person approves, and every step is logged. Start with the cases the engine could not settle.
        </p>
      </div>

      <StatCards columns={4} stats={[
        { icon: RiInboxLine, label: "To decide", value: String(counts.decide), delta: "needs you", deltaColor: "neutral", tone: "orange" },
        { icon: RiUserFollowLine, label: "To approve", value: String(counts.approve), delta: "four-eyes", deltaColor: "neutral", tone: "purple" },
        { icon: RiFlaskLine, label: "QA sample", value: String(counts.qa), delta: "1 in 10 clears", deltaColor: "neutral", tone: "sky" },
        { icon: RiCheckboxCircleLine, label: "Closed", value: String(counts.closed), delta: pct(counts.closed), deltaColor: "lime", tone: "emerald" },
      ]} />

      <div className="flex flex-wrap gap-3">
        <Button variant="primary" onClick={() => onOpen("decide")}>Start reviewing ({counts.decide})</Button>
        {counts.approve > 0 && <Button variant="secondary" onClick={() => onOpen("approve")}>Approve decisions ({counts.approve})</Button>}
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <Card title="What the engine found">
          <div className="flex h-3 overflow-hidden rounded-full bg-background-secondary-default">
            <div className="bg-lime-500" style={{ width: pct(n("DIFFERENT_ENTITY")) }} />
            <div className="bg-amber-400" style={{ width: pct(n("REVIEW")) }} />
            <div className="bg-rose-500" style={{ width: pct(n("SAME_ENTITY")) }} />
          </div>
          <dl className="mt-4 grid grid-cols-3 gap-2 text-center">
            <div><dt className="text-caption-1-medium text-text-tertiary">Clear</dt><dd className="text-title-3-semibold text-text-primary">{n("DIFFERENT_ENTITY")}</dd></div>
            <div><dt className="text-caption-1-medium text-text-tertiary">Review</dt><dd className="text-title-3-semibold text-text-primary">{n("REVIEW")}</dd></div>
            <div><dt className="text-caption-1-medium text-text-tertiary">Match</dt><dd className="text-title-3-semibold text-text-primary">{n("SAME_ENTITY")}</dd></div>
          </dl>
          {summary.practice.n > 0 && (
            <p className="mt-4 text-body-2-regular text-text-secondary">
              On the {summary.practice.n} practice labels: {summary.practice.right} right, score {summary.practice.score}%, <b className="text-text-primary">{summary.practice.unsafe} unsafe clearances</b>.
            </p>
          )}
        </Card>
        <Card title="How a case is decided">
          <ol className="flex list-decimal flex-col gap-2 pl-5 text-body-2-regular text-text-secondary">
            <li><b className="text-text-primary">Rules engine</b> applies the bank's SOP and cites every record it used.</li>
            <li><b className="text-text-primary">Grok</b> {summary.llm.startsWith("rules") ? "is off (no key), so the rules decide alone." : "makes its own call and re-reads every clearance; it can never clear a hit by itself."}</li>
            <li><b className="text-text-primary">You</b> decide with a reason and the records you rely on.</li>
            <li><b className="text-text-primary">A second reviewer</b> approves or returns it.</li>
          </ol>
          {mi && mi.decisions > 0 && (
            <p className="mt-4 text-body-2-regular text-text-secondary">So far: {mi.decisions} decisions, {mi.approvals} approved, {mi.agreement_rate}% agreed with the engine.</p>
          )}
        </Card>
      </div>
    </div>
  );
}
