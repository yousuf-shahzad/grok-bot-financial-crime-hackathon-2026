import { useCallback, useEffect, useMemo, useState } from "react";
import { RiCheckLine, RiCloseLine, RiQuestionLine, RiFileTextLine, RiRobot2Line, RiArrowRightLine, RiLightbulbLine, RiArrowLeftLine } from "@remixicon/react";
import { Tabs, TabList, Tab, TabPanel } from "@/components/base/tabs/tabs";
import { Checkbox } from "@/components/base/checkbox/checkbox";
import { Spinner } from "@/components/base/spinner/spinner";
import { cx } from "@/utils/cx";
import { api, type CaseDetail, type CompRow, type HumanDecision } from "./api";
import { BUCKET, Card, Empty, HUM, RecordLink, StatusChip, SYS, plain, useApp } from "./ui";
import CourtPanel, { type CourtState } from "./Court";
import DecisionCard from "./Decision";

const VERDICT = {
  agree: { label: "Same", icon: RiCheckLine, cls: "text-rose-600 bg-rose-50 dark:bg-rose-950/40 dark:text-rose-300" },
  contradict: { label: "Different", icon: RiCloseLine, cls: "text-lime-700 bg-lime-50 dark:bg-lime-950/40 dark:text-lime-300" },
  unknown: { label: "Unknown", icon: RiQuestionLine, cls: "text-text-tertiary bg-background-secondary-default" },
};

function Values({ items }: { items: (CompRow["customer"][number] | string)[] }) {
  if (!items.length) return <span className="text-text-tertiary">unknown</span>;
  return (
    <div className="flex flex-col gap-1">
      {items.slice(0, 3).map((f, i) => typeof f === "string" ? <span key={i}>{f}</span> : (
        <span key={i} className="flex flex-wrap items-center gap-2"><span>{f.value}</span><RecordLink id={f.source} /></span>
      ))}
      {items.length > 3 && <span className="text-caption-1-regular text-text-tertiary">+{items.length - 3} more</span>}
    </div>
  );
}

function Step({ title, children, tone }: { title: string; children: React.ReactNode; tone?: string }) {
  return (
    <div className={cx("flex min-w-[10rem] flex-1 flex-col gap-1.5 rounded-lg border border-separator-border px-4 py-3", tone)}>
      <span className="text-caption-1-semibold text-text-tertiary uppercase">{title}</span>
      {children}
    </div>
  );
}

export default function CaseView({ hitId, onChanged, onBack, backLabel }: { hitId: string; onChanged: () => void; onBack: () => void; backLabel: string }) {
  const { blind } = useApp();
  const [d, setD] = useState<CaseDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [codes, setCodes] = useState<Record<HumanDecision, string[]> | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [court, setCourt] = useState<CourtState>({});
  const [chosen, setChosen] = useState<HumanDecision | null>(null);

  const load = useCallback(() => {
    api.case(hitId).then((x) => { setD(x); setPicked(x.records.filter((r) => r.default).map((r) => r.id)); }).catch((e) => setErr(e.message));
  }, [hitId]);
  useEffect(() => { load(); api.codes().then(setCodes).catch(() => {}); }, [load]);
  const groups = useMemo(() => {
    const g: Record<string, CaseDetail["records"]> = {};
    for (const r of d?.records || []) (g[r.group] ||= []).push(r);
    return g;
  }, [d]);

  if (err) return <Empty>{err}</Empty>;
  if (!d) return <div className="flex items-center gap-3 p-10"><Spinner /><span className="text-text-secondary">Loading case...</span></div>;

  const sys = d.decision;
  const hidden = blind && !chosen && !["pending_approval", "done"].includes(d.workflow);
  const dual = (d as unknown as { dual?: { llm?: { decision: keyof typeof SYS; reason_code?: string } | null; screener?: { error_in?: string; explanation?: string } | null } }).dual;
  const name = d.profile.names[0]?.value || hitId;

  return (
    <div className="mx-auto grid max-w-[90rem] gap-8 px-10 py-10 xl:grid-cols-[minmax(0,1fr)_23rem]">
      <div className="flex min-w-0 flex-col gap-8">
        <button type="button" onClick={onBack} className="-mb-2 inline-flex items-center gap-1 self-start text-body-2-medium text-text-secondary hover:text-text-primary"><RiArrowLeftLine size={16} />Back to {backLabel}</button>
        {/* Header */}
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="font-display text-[2.25rem] leading-tight text-navy dark:text-text-primary">{name}</h1>
              <StatusChip color={BUCKET[d.workflow].color}>{BUCKET[d.workflow].label}</StatusChip>
            </div>
            <p className="mt-1 text-body-regular text-text-secondary">
              {plain(d.profile.listing_kind) || "Watchlist profile"} · screened as <b className="text-text-primary">{String(d.alert.customer_name || "unknown")}</b>
              {d.alert.dob ? `, born ${String(d.alert.dob)}` : ""}{d.alert.country ? `, ${String(d.alert.country)}` : ""}
            </p>
          </div>
          <a href={`/api/report/${hitId}.md`} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 rounded-lg border border-separator-border px-3 py-1.5 text-body-2-medium text-text-secondary hover:text-text-primary"><RiFileTextLine size={16} />Case report</a>
        </div>

        {/* Several customers fit this alert: show them side by side so look-alike records are told apart */}
        {(d.people?.length || 0) > 1 && (
          <section className="rounded-2xl border border-gold-300 bg-gold-50 p-6 dark:bg-transparent">
            <h3 className="text-headline-semibold text-text-primary">{d.people!.length} customers fit this alert</h3>
            <p className="mt-1 text-body-2-regular text-text-secondary">
              They share a name but are different people (records are only merged on the same phone and full date of birth, or the same document number).
              {new Set(d.people!.map((p) => p.decision)).size > 1 ? " They lead to different answers, so the bank's rules send the hit to a person." : " They all lead to the same answer."}
            </p>
            <div className="mt-4 overflow-x-auto rounded-xl border border-separator-border bg-background-primary-default">
              <table className="w-full text-left text-body-2-regular">
                <thead className="text-caption-1-semibold text-text-tertiary uppercase">
                  <tr className="border-b border-separator-border"><th className="px-4 py-3">Customer</th><th className="px-4 py-3">Name</th><th className="px-4 py-3">Date of birth</th><th className="px-4 py-3">Countries</th><th className="px-4 py-3">On its own</th></tr>
                </thead>
                <tbody>
                  {d.people!.map((p) => (
                    <tr key={p.person_id} className="border-b border-separator-border last:border-0">
                      <td className="px-4 py-3"><span className="flex flex-wrap gap-1">{p.record_ids.map((r) => <RecordLink key={r} id={r} />)}</span></td>
                      <td className="px-4 py-3 text-text-primary">{p.name || "unknown"}</td>
                      <td className="px-4 py-3 font-medium text-text-primary">{p.dob || "unknown"}</td>
                      <td className="px-4 py-3 text-text-secondary">{p.countries.join(", ") || "unknown"}</td>
                      <td className="px-4 py-3"><span className="flex flex-col items-start gap-0.5"><StatusChip color={SYS[p.decision].color}>{SYS[p.decision].label}</StatusChip><span className="text-caption-1-regular text-text-tertiary">{plain(p.reason_code)}</span></span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {/* Verdict strip: who said what */}
        {hidden ? (
          <div className="rounded-lg border border-dashed border-separator-border px-4 py-3 text-body-2-regular text-text-secondary">
            Blind review is on. The machine's view appears once you pick a decision on the right.
          </div>
        ) : (
          <div className="flex flex-wrap items-stretch gap-2">
            <Step title="Rules engine"><span className="flex flex-col items-start gap-1"><StatusChip color={SYS[sys.decision].color}>{SYS[sys.decision].label}</StatusChip><span className="text-caption-1-regular text-text-secondary">{plain(sys.reason_code)}</span></span></Step>
            <RiArrowRightLine className="hidden self-center text-text-tertiary md:block" size={18} />
            <Step title="Grok judge">
              {dual?.llm ? <span className="flex flex-col items-start gap-1"><StatusChip color={SYS[dual.llm.decision].color}>{SYS[dual.llm.decision].label}</StatusChip><span className="text-caption-1-regular text-text-secondary">{dual.llm.decision === sys.decision ? "agrees" : "disagrees"}</span></span>
                : d.crossexam.downgraded ? <span className="text-caption-1-regular text-text-secondary">Re-read the evidence and blocked a clearance</span>
                : <span className="text-caption-1-regular text-text-tertiary">{d.crossexam.provider.startsWith("rules") ? "Off (no key)" : "No objection"}</span>}
            </Step>
            {dual?.screener && (<>
              <RiArrowRightLine className="hidden self-center text-text-tertiary md:block" size={18} />
              <Step title="Screening agent"><span className="text-caption-1-regular text-text-secondary">{dual.screener.error_in === "neither" ? "No clear error: sent to review" : `Error found in ${dual.screener.error_in} output`}</span></Step>
            </>)}
            <RiArrowRightLine className="hidden self-center text-text-tertiary md:block" size={18} />
            <Step title="Recommendation" tone="bg-background-secondary-default"><StatusChip color={SYS[sys.decision].color}>{SYS[sys.decision].label}</StatusChip></Step>
          </div>
        )}

        <Tabs defaultSelectedKey="summary">
          <TabList aria-label="Case sections">
            <Tab id="summary">Summary</Tab>
            <Tab id="evidence" count={d.records.length}>Evidence</Tab>
            <Tab id="court" icon={RiRobot2Line}>AI court</Tab>
            <Tab id="history" count={d.history.length || undefined}>History</Tab>
          </TabList>

          <TabPanel id="summary" className="flex flex-col gap-7 pt-7">
            {!hidden && (
              <Card title="Why">
                <p className="text-body-regular text-text-primary">{sys.reason}</p>
                {sys.evidence.length > 0 && <div className="mt-3 flex flex-wrap items-center gap-2"><span className="text-caption-1-regular text-text-tertiary">Based on</span>{sys.evidence.map((e) => <RecordLink key={e} id={e} />)}</div>}
                {d.label && <p className={cx("mt-3 text-caption-1-medium", d.label.decision === sys.decision ? "text-lime-700 dark:text-lime-300" : "text-rose-600")}>Practice answer: {SYS[d.label.decision].label} ({d.label.decision === sys.decision ? "agrees" : "differs"})</p>}
              </Card>
            )}
            <Card title="Customer vs watchlist hit" pad={false}>
              <table className="w-full table-fixed text-left text-body-2-regular">
                <thead className="text-caption-1-semibold text-text-tertiary uppercase">
                  <tr className="border-b border-separator-border"><th className="w-36 px-5 py-3">Field</th><th className="px-5 py-3">Our customer</th><th className="px-5 py-3">Watchlist hit</th><th className="w-32 px-5 py-3">Result</th></tr>
                </thead>
                <tbody>
                  {d.comparison.map((r) => {
                    const v = VERDICT[r.status];
                    return (
                      <tr key={r.field} className="border-b border-separator-border align-top last:border-0">
                        <td className="px-5 py-4 text-body-2-semibold text-text-primary">{r.field}</td>
                        <td className="px-5 py-4 text-text-primary"><Values items={r.customer} /></td>
                        <td className="px-5 py-4 text-text-primary"><Values items={r.hit} /></td>
                        <td className="px-5 py-4" title={r.note || undefined}><span className={cx("inline-flex items-center gap-1 rounded-md px-2 py-1 text-caption-1-semibold", v.cls)}><v.icon size={14} />{v.label}</span></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </Card>
            {d.profile.missing?.length > 0 && d.workflow !== "done" && (
              <div className="flex gap-3 rounded-lg border border-amber-300/60 bg-amber-50 px-4 py-3 dark:bg-amber-950/30">
                <RiLightbulbLine className="mt-0.5 shrink-0 text-amber-600" size={18} />
                <div><p className="text-body-2-semibold text-text-primary">What would settle this</p>
                  <ul className="mt-1 list-disc pl-5 text-body-2-regular text-text-secondary">{d.profile.missing.map((m, i) => <li key={i}>{plain(m)}</li>)}</ul></div>
              </div>
            )}
          </TabPanel>

          <TabPanel id="evidence" className="flex flex-col gap-4 pt-6">
            <p className="text-body-2-regular text-text-secondary">Tick the records the AI court may read. Nothing else is sent to the model.</p>
            {Object.entries(groups).map(([g, recs]) => (
              <Card key={g} title={g} aside={<span className="text-caption-1-regular text-text-tertiary">{recs.filter((r) => picked.includes(r.id)).length} of {recs.length} selected</span>}>
                <ul className="flex flex-col gap-3">
                  {recs.map((r) => (
                    <li key={r.id} className="flex items-start gap-3">
                      <Checkbox aria-label={`Use ${r.id}`} isSelected={picked.includes(r.id)} onChange={(on) => setPicked(on ? [...picked, r.id] : picked.filter((x) => x !== r.id))} />
                      <div className="min-w-0 flex-1"><RecordLink id={r.id} /><p className="mt-1 line-clamp-2 text-caption-1-regular text-text-secondary">{r.text.replace(/\n/g, " · ")}</p></div>
                    </li>
                  ))}
                </ul>
              </Card>
            ))}
          </TabPanel>

          <TabPanel id="court" className="pt-6">
            <CourtPanel detail={d} picked={picked} court={court} setCourt={setCourt} />
          </TabPanel>

          <TabPanel id="history" className="pt-6">
            <Card title="Audit trail" aside={<span className="text-caption-1-regular text-text-tertiary">cannot be edited</span>}>
              {!d.history.length ? <Empty>No human action yet.</Empty> : (
                <ol className="flex flex-col gap-4">
                  {d.history.map((h) => (
                    <li key={h.id} className="border-l-2 border-separator-border pl-4">
                      <p className="text-body-2-semibold text-text-primary">{h.action === "DECIDE" ? HUM[h.decision as HumanDecision]?.label : plain(h.action)} <span className="text-caption-1-regular text-text-tertiary">by {h.reviewer} · {h.created_at.replace("T", " ")}</span></p>
                      {h.reason_code && <p className="text-caption-1-regular text-text-tertiary">{plain(h.reason_code)}{h.record_ids.length ? ` · cites ${h.record_ids.join(", ")}` : ""}</p>}
                      <p className="mt-1 text-body-2-regular whitespace-pre-wrap text-text-secondary">{h.rationale}</p>
                    </li>
                  ))}
                </ol>
              )}
            </Card>
          </TabPanel>
        </Tabs>
      </div>

      <div className="xl:sticky xl:top-8 xl:self-start">
        <DecisionCard detail={d} codes={codes} court={court} picked={picked} onChoose={setChosen} onDone={() => { load(); onChanged(); }} />
      </div>
    </div>
  );
}
