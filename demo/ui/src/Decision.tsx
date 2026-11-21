import { useEffect, useState } from "react";
import { RiCheckLine, RiArrowGoBackLine, RiLockLine } from "@remixicon/react";
import { Button } from "@/components/base/buttons/button";
import { Select, SelectItem } from "@/components/base/select/select";
import { Textarea } from "@/components/base/textarea/textarea";
import { Checkbox } from "@/components/base/checkbox/checkbox";
import { cx } from "@/utils/cx";
import { api, type CaseDetail, type HumanDecision, type SystemDecision } from "./api";
import { HUM, plain, useApp } from "./ui";
import type { CourtState } from "./Court";

const SYS_TO_HUM: Record<SystemDecision, HumanDecision> = { DIFFERENT_ENTITY: "CLEAR", SAME_ENTITY: "CONFIRM", REVIEW: "ESCALATE" };
const CHOICES: { id: HumanDecision; label: string; help: string; cls: string }[] = [
  { id: "CLEAR", label: "Clear", help: "Different person", cls: "data-[on=true]:border-lime-500 data-[on=true]:bg-lime-50 dark:data-[on=true]:bg-lime-950/40" },
  { id: "CONFIRM", label: "Match", help: "Same person", cls: "data-[on=true]:border-rose-500 data-[on=true]:bg-rose-50 dark:data-[on=true]:bg-rose-950/40" },
  { id: "ESCALATE", label: "Escalate", help: "Need more info", cls: "data-[on=true]:border-amber-500 data-[on=true]:bg-amber-50 dark:data-[on=true]:bg-amber-950/40" },
];

export default function DecisionCard({ detail, codes, court, picked, onChoose, onDone }: {
  detail: CaseDetail; codes: Record<HumanDecision, string[]> | null; court: CourtState; picked: string[];
  onChoose: (d: HumanDecision | null) => void; onDone: () => void;
}) {
  const { reviewer, toast } = useApp();
  const [decision, setDecision] = useState<HumanDecision | null>(null);
  const [code, setCode] = useState<string | null>(null);
  const [cited, setCited] = useState<string[]>(detail.decision.evidence.filter((e) => detail.records.some((r) => r.id === e)));
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const wf = detail.workflow;
  const maker = [...detail.history].reverse().find((h) => h.action === "DECIDE");

  useEffect(() => { onChoose(decision); }, [decision, onChoose]);
  useEffect(() => {
    if (!decision || !codes) return;
    const s = detail.decision;
    setCode(SYS_TO_HUM[s.decision] === decision && codes[decision].includes(s.reason_code) ? s.reason_code : codes[decision][0]);
  }, [decision, codes, detail.decision]);

  const send = async (body: Record<string, unknown>, ok: string) => {
    if (!reviewer) return;
    setBusy(true);
    try {
      const r = await api.review({ hit_id: detail.decision.hit_id, reviewer: reviewer.name, role: reviewer.role, ...body });
      toast(ok, `Case is now ${plain(r.workflow).toLowerCase()}. Logged under ${reviewer.name}.`);
      onDone();
    } catch (e) { toast("Not saved", (e as Error).message, false); } finally { setBusy(false); }
  };

  const shell = "rounded-2xl border border-separator-border border-t-4 border-t-gold-500 bg-background-primary-default p-6";
  if (wf === "done") {
    const chk = [...detail.history].reverse().find((h) => h.action === "APPROVE");
    return <div className={shell}><p className="flex items-center gap-2 text-headline-semibold text-text-primary"><RiLockLine size={18} />Closed</p>
      <p className="mt-2 text-body-2-regular text-text-secondary">{HUM[maker?.decision as HumanDecision]?.label} by {maker?.reviewer}, approved by {chk?.reviewer}.</p></div>;
  }

  if (wf === "pending_approval" && maker) {
    const same = reviewer && reviewer.name.toLowerCase() === maker.reviewer.toLowerCase();
    return (
      <div className={shell}>
        <p className="text-headline-semibold text-text-primary">Approve this decision?</p>
        <p className="mt-2 text-body-2-regular text-text-secondary"><b className="text-text-primary">{maker.reviewer}</b> chose <b className="text-text-primary">{HUM[maker.decision as HumanDecision]?.label}</b> ({plain(maker.reason_code)}).</p>
        <p className="mt-2 rounded-lg bg-background-secondary-default p-3 text-body-2-regular whitespace-pre-wrap text-text-primary">{maker.rationale}</p>
        {same ? <p className="mt-4 text-body-2-regular text-amber-700 dark:text-amber-300">You made this decision. A different person has to approve it.</p> : (
          <div className="mt-4 flex flex-col gap-3">
            <Textarea label="Your note" placeholder="Why you approve, or what needs fixing" value={note} onChange={setNote} rows={3} />
            <div className="flex gap-2">
              <Button variant="primary" leadingIcon={RiCheckLine} disabled={busy || note.trim().length < 10} onClick={() => send({ action: "APPROVE", rationale: note }, "Approved")}>Approve</Button>
              <Button variant="secondary" leadingIcon={RiArrowGoBackLine} disabled={busy || note.trim().length < 10} onClick={() => send({ action: "RETURN", rationale: note }, "Returned")}>Return</Button>
            </div>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className={shell}>
      <p className="text-headline-semibold text-text-primary">Your decision</p>
      <p className="mt-1 text-caption-1-regular text-text-secondary">{wf === "returned" ? "A checker sent this back. See History, then decide again." : "A second reviewer will approve it."}</p>
      <div className="mt-4 grid grid-cols-3 gap-2" role="radiogroup" aria-label="Decision">
        {CHOICES.map((c) => (
          <button key={c.id} type="button" role="radio" aria-checked={decision === c.id} data-on={decision === c.id} onClick={() => setDecision(c.id)}
            className={cx("flex flex-col items-center rounded-lg border border-separator-border px-2 py-3 text-center hover:bg-background-secondary-default focus-visible:outline-2 focus-visible:outline-accent-500", c.cls)}>
            <span className="text-body-semibold text-text-primary">{c.label}</span>
            <span className="text-caption-2-regular text-text-tertiary">{c.help}</span>
          </button>
        ))}
      </div>

      {decision && (
        <div className="mt-5 flex flex-col gap-4">
          <Select label="Reason" selectedKey={code} onSelectionChange={(k) => setCode(String(k))} className="w-full" triggerClassName="w-full">
            {(codes?.[decision] || []).map((c) => <SelectItem key={c} id={c}>{plain(c)}</SelectItem>)}
          </Select>
          <div>
            <p className="mb-2 text-body-2-medium text-text-primary">Records you rely on {decision !== "ESCALATE" && <span className="text-text-tertiary">(at least one)</span>}</p>
            <div className="flex max-h-40 flex-col gap-2 overflow-y-auto rounded-lg border border-separator-border p-3">
              {detail.records.map((r) => (
                <Checkbox key={r.id} isSelected={cited.includes(r.id)} onChange={(on) => setCited(on ? [...cited, r.id] : cited.filter((x) => x !== r.id))}>
                  <span className="font-mono text-caption-1-regular text-text-secondary">{r.id}</span> <span className="text-caption-1-regular text-text-tertiary">{r.kind.replace("_", " ")}</span>
                </Checkbox>
              ))}
            </div>
            {picked.length > 0 && <button type="button" className="mt-2 text-caption-1-medium text-accent-600" onClick={() => setCited(Array.from(new Set([...cited, ...picked])))}>Add the records you gave the court</button>}
          </div>
          <Textarea label="Rationale" placeholder="The facts that decide it, in your own words" value={note} onChange={setNote} rows={4} />
          {court.adjudicator?.summary && <button type="button" className="-mt-2 self-start text-caption-1-medium text-accent-600" onClick={() => setNote((n) => (n ? n + "\n\n" : "") + "Adjudicator (AI, advisory): " + court.adjudicator!.summary)}>Insert the adjudicator's summary</button>}
          <Button variant={decision === "CLEAR" || decision === "ESCALATE" ? "primary" : "danger"} disabled={busy || !reviewer || !code || note.trim().length < 10 || (decision !== "ESCALATE" && !cited.length)}
            onClick={() => send({ action: "DECIDE", decision, reason_code: code, record_ids: cited, rationale: note, court: court.adjudicator ? court : undefined }, decision === "ESCALATE" ? "Escalated" : "Sent for approval")}>
            {decision === "ESCALATE" ? "Escalate" : `Submit ${HUM[decision].label.toLowerCase()} for approval`}
          </Button>
        </div>
      )}
    </div>
  );
}
