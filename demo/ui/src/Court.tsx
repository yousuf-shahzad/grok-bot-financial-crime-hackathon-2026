import { useState } from "react";
import { RiAuctionLine, RiSparklingLine } from "@remixicon/react";
import { Button } from "@/components/base/buttons/button";
import { Spinner } from "@/components/base/spinner/spinner";
import { api, type CaseDetail, type CourtOut } from "./api";
import { Card, Empty, HUM, RecordLink, StatusChip, plain } from "./ui";

export type CourtState = { prosecution?: CourtOut; defence?: CourtOut; adjudicator?: CourtOut };

function Side({ title, tone, out, rules }: { title: string; tone: string; out?: CourtOut; rules: { text: string; on: boolean }[] }) {
  return (
    <Card title={<span className={tone}>{title}</span>}>
      {out?.error ? <p className="text-body-2-regular text-rose-600">{out.error}</p> : out?.position ? (
        <div className="flex flex-col gap-3">
          <p className="text-body-2-semibold text-text-primary">{out.position}</p>
          <ul className="flex flex-col gap-2">
            {(out.points || []).map((p, i) => (
              <li key={i} className="text-body-2-regular text-text-secondary">{p.claim}
                <span className="ml-1 inline-flex flex-wrap gap-1 align-middle">{p.evidence_ids.map((e) => <RecordLink key={e} id={e} />)}</span></li>
            ))}
          </ul>
          {!!out.gaps?.length && <p className="text-caption-1-regular text-amber-700 dark:text-amber-300">Unknown: {out.gaps.join("; ")}</p>}
        </div>
      ) : (
        <ul className="flex flex-col gap-1.5">
          <li className="text-caption-1-semibold text-text-tertiary uppercase">From the rules engine</li>
          {rules.length ? rules.map((r, i) => <li key={i} className={r.on ? "text-body-2-regular text-text-primary" : "text-body-2-regular text-text-tertiary"}>{r.on ? "• " : "◦ "}{r.text}</li>)
            : <li className="text-body-2-regular text-text-tertiary">Nothing on this side.</li>}
        </ul>
      )}
    </Card>
  );
}

export default function CourtPanel({ detail, picked, court, setCourt }: { detail: CaseDetail; picked: string[]; court: CourtState; setCourt: (c: CourtState) => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const trial = detail.court[0];
  const call = async (role: string, prior?: CourtState) => {
    const body: Record<string, unknown> = { hit_id: detail.decision.hit_id, role, record_ids: picked };
    if (role === "adjudicator") body.prior = { prosecution: prior?.prosecution || {}, defence: prior?.defence || {} };
    try { return await api.court(body); } catch (e) { return { error: (e as Error).message } as CourtOut; }
  };
  const convene = async () => {
    setBusy("Both sides are arguing");
    const [p, d] = await Promise.all([call("prosecution"), call("defence")]);
    setCourt({ prosecution: p, defence: d });
    setBusy("The adjudicator is weighing them");
    const a = await call("adjudicator", { prosecution: p, defence: d });
    setCourt({ prosecution: p, defence: d, adjudicator: a });
    setBusy(null);
  };
  const adj = court.adjudicator;
  if (!trial && !detail.court_available) return <Empty>No customer was found for this alert, so there is nothing to argue.</Empty>;

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-separator-border bg-background-primary-default px-5 py-4">
        <div>
          <p className="text-body-semibold text-text-primary">Ask the AI court</p>
          <p className="text-caption-1-regular text-text-secondary">Prosecution and defence argue from the {picked.length} records ticked under Evidence; the adjudicator summarises. Advisory only: you decide.</p>
        </div>
        {busy ? <span className="flex items-center gap-2 text-body-2-regular text-text-secondary"><Spinner size="sm" />{busy}...</span>
          : <Button variant="primary" leadingIcon={RiSparklingLine} disabled={!detail.court_available || !picked.length} onClick={convene}>Convene the court</Button>}
      </div>
      {!detail.court_available && <p className="text-caption-1-regular text-text-tertiary">The AI court needs an LLM key (XAI_API_KEY in .env). The rules view below still works.</p>}

      {adj && (
        <Card title={<span className="flex items-center gap-2"><RiAuctionLine size={18} />Adjudicator's summary</span>} aside={<span className="text-caption-1-regular text-text-tertiary">AI-written</span>}>
          {adj.error ? <p className="text-body-2-regular text-rose-600">{adj.error}</p> : (
            <div className="flex flex-col gap-3">
              <p className="text-body-regular text-text-primary">{adj.summary}</p>
              <div className="flex flex-wrap items-center gap-2">
                {adj.suggested_disposition && <StatusChip color={HUM[adj.suggested_disposition].color}>Suggests {HUM[adj.suggested_disposition].label.toLowerCase()}</StatusChip>}
                {adj.confidence && <span className="text-caption-1-regular text-text-secondary">confidence {adj.confidence}</span>}
                {adj.sop_rule && <span className="text-caption-1-regular text-text-tertiary">· {plain(adj.sop_rule)}</span>}
              </div>
              {!!adj.what_would_settle?.length && <ul className="list-disc pl-5 text-body-2-regular text-text-secondary">{adj.what_would_settle.map((w, i) => <li key={i}>{w}</li>)}</ul>}
            </div>
          )}
        </Card>
      )}

      <div className="grid gap-5 lg:grid-cols-2">
        <Side title="Prosecution: it is the customer" tone="text-rose-600 dark:text-rose-300" out={court.prosecution}
          rules={(trial?.prosecution || []).map((a) => ({ text: `${a.what}: ${a.detail}`, on: true }))} />
        <Side title="Defence: it is someone else" tone="text-lime-700 dark:text-lime-300" out={court.defence}
          rules={(trial?.defence || []).map((a) => ({ text: `${a.rule}${a.holds ? " (holds)" : ""}`, on: !!a.holds }))} />
      </div>
    </div>
  );
}
