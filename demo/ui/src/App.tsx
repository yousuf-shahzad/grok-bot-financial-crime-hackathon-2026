import { useCallback, useEffect, useMemo, useState } from "react";
import {
  RiHome5Line, RiInboxLine, RiUserFollowLine, RiFlaskLine, RiAlertLine, RiCheckboxCircleLine, RiListCheck2, RiDownloadLine, RiShieldCheckLine,
} from "@remixicon/react";
import { Button } from "@/components/base/buttons/button";
import { SearchField } from "@/components/base/search-field/search-field";
import { Spinner } from "@/components/base/spinner/spinner";
import { Modal, ModalBody, ModalDialog, ModalHeader, ModalFooter } from "@/components/base/modal/modal";
import { Select, SelectItem } from "@/components/base/select/select";
import { Input } from "@/components/base/input/input";
import { Notification } from "@/components/base/notification/notification";
import { api, type Bucket, type CaseRow, type Summary } from "./api";
import { AppCtx, type Reviewer } from "./ui";
import Sidebar, { type NavEntry } from "./Sidebar";
import QueueTable from "./QueueTable";
import Overview from "./Overview";
import CaseView from "./CaseView";

export type QueueKey = "overview" | "decide" | "approve" | "qa" | "cleared" | "escalated" | "closed" | "all";
const QUEUES: { key: QueueKey; label: string; icon: NavEntry["icon"]; buckets: Bucket[] | null; qa?: boolean; hint: string }[] = [
  { key: "decide", label: "To decide", icon: RiInboxLine, buckets: ["needs_decision", "returned", "proposed_match"], hint: "The engine could not settle these, or thinks the hit is your customer." },
  { key: "approve", label: "To approve", icon: RiUserFollowLine, buckets: ["pending_approval"], hint: "A colleague has decided. A second person signs it off." },
  { key: "qa", label: "QA sample", icon: RiFlaskLine, buckets: ["proposed_clear"], qa: true, hint: "One in ten engine clearances, for a human spot-check." },
  { key: "cleared", label: "Cleared by Tryll", icon: RiShieldCheckLine, buckets: ["proposed_clear"], hint: "Every hit Tryll cleared because the bank's rules found a named contradiction. Open one to check the evidence, confirm the clearance, or overturn it." },
  { key: "escalated", label: "Escalated", icon: RiAlertLine, buckets: ["escalated"], hint: "Waiting for more information." },
  { key: "closed", label: "Closed", icon: RiCheckboxCircleLine, buckets: ["done"], hint: "Decided and approved by two people." },
  { key: "all", label: "All hits", icon: RiListCheck2, buckets: null, hint: "Every hit, including the engine's clearances." },
];

function load<T>(k: string, d: T): T { try { const v = localStorage.getItem(k); return v ? (JSON.parse(v) as T) : d; } catch { return d; } }
function save(k: string, v: unknown) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* storage blocked */ } }

function SignIn({ onDone }: { onDone: (r: Reviewer) => void }) {
  const [name, setName] = useState("");
  const [role, setRole] = useState<Reviewer["role"]>("analyst");
  return (
    <Modal isOpen isDismissable={false} size="sm">
      <ModalDialog aria-label="Sign in">
        <div className="flex justify-center px-6 pt-6"><img src="/tryll-logo.webp" alt="Tryll" className="h-20 w-auto" /></div>
        <ModalHeader title="Welcome to Tryll" description="Sign in with your name. Every decision is recorded under it, in a log that cannot be edited." showCloseButton={false} />
        <ModalBody>
          <div className="flex flex-col gap-4">
            <Input label="Name" placeholder="e.g. Alex Morgan" value={name} onChange={setName} autoFocus />
            <Select label="Role" selectedKey={role} onSelectionChange={(k) => setRole(k as Reviewer["role"])} className="w-full" triggerClassName="w-full">
              <SelectItem id="analyst">Analyst</SelectItem>
              <SelectItem id="checker">Checker</SelectItem>
              <SelectItem id="qa">QA reviewer</SelectItem>
            </Select>
          </div>
        </ModalBody>
        <ModalFooter><Button variant="primary" disabled={name.trim().length < 2} onClick={() => onDone({ name: name.trim(), role })}>Continue</Button></ModalFooter>
      </ModalDialog>
    </Modal>
  );
}

export default function App() {
  const [ready, setReady] = useState<string | true>("connecting");
  const [summary, setSummary] = useState<Summary | null>(null);
  const [rows, setRows] = useState<CaseRow[]>([]);
  const [queue, setQueueState] = useState<QueueKey>(() => load("tryll-queue", "overview"));
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [reviewer, setReviewerState] = useState<Reviewer | null>(() => load("tryll-reviewer", null));
  const [blind, setBlindState] = useState<boolean>(() => load("tryll-blind", false));
  const [tick, setTick] = useState(0);
  const [record, setRecord] = useState<{ id: string; kind: string; row: Record<string, unknown> } | null>(null);
  const [toasts, setToasts] = useState<{ id: number; t: string; d?: string; ok: boolean }[]>([]);

  const setQueue = (q: string) => { setQueueState(q as QueueKey); save("tryll-queue", q); setSelected(null); setSearch(""); };
  const setReviewer = (r: Reviewer | null) => { setReviewerState(r); save("tryll-reviewer", r); };
  const setBlind = (b: boolean) => { setBlindState(b); save("tryll-blind", b); };
  const toast = useCallback((t: string, d?: string, ok = true) => {
    const id = Date.now() + Math.random();
    setToasts((x) => [...x, { id, t, d, ok }]);
    setTimeout(() => setToasts((x) => x.filter((y) => y.id !== id)), 4500);
  }, []);

  useEffect(() => {
    let stop = false;
    const poll = async () => {
      try { const s = await api.status(); if (s.ready) { setReady(true); return; } setReady(s.status); } catch { setReady("waiting for the server"); }
      if (!stop) setTimeout(poll, 800);
    };
    poll();
    return () => { stop = true; };
  }, []);
  useEffect(() => {
    if (ready !== true) return;
    api.summary().then(setSummary).catch(() => {});
    api.cases({}).then((r) => setRows(r.rows)).catch(() => {});
  }, [ready, tick]);

  const openRecord = useCallback((id: string) => {
    setRecord({ id, kind: "loading", row: {} });
    api.record(id).then(setRecord).catch(() => setRecord({ id, kind: "not found", row: {} }));
  }, []);

  const counts = useMemo(() => {
    const c = {} as Record<QueueKey, number>;
    for (const q of QUEUES) c[q.key] = rows.filter((r) => !q.buckets || (q.buckets.includes(r.bucket) && (!q.qa || r.qa_sample))).length;
    return c;
  }, [rows]);
  const current = QUEUES.find((q) => q.key === queue);
  const visible = useMemo(() => {
    if (!current) return [];
    const s = search.trim().toLowerCase();
    return rows.filter((r) => (!current.buckets || (current.buckets.includes(r.bucket) && (!current.qa || r.qa_sample)))
      && (!s || `${r.hit_id} ${r.alert_id} ${r.hit_name} ${r.screened_name}`.toLowerCase().includes(s)));
  }, [rows, current, search]);

  if (ready !== true) {
    return <div className="flex h-full flex-col items-center justify-center gap-3"><Spinner size="lg" /><p className="text-body-regular text-text-secondary">Tryll is reading the alerts: {ready}...</p></div>;
  }

  return (
    <AppCtx.Provider value={{ openRecord, reviewer, blind, toast }}>
      {!reviewer && <SignIn onDone={setReviewer} />}
      <div className="flex h-full min-h-0 bg-background-secondary-default">
        <Sidebar main={{ key: "overview", label: "Home", icon: RiHome5Line }}
          queues={QUEUES.map((q) => ({ key: q.key, label: q.label, icon: q.icon, count: counts[q.key] }))}
          selected={queue} onSelect={setQueue} reviewer={reviewer} onSignOut={() => setReviewer(null)} blind={blind} setBlind={setBlind} />

        <main className="min-w-0 flex-1 overflow-y-auto">
          {selected ? (
            <CaseView key={selected + tick} hitId={selected} backLabel={current ? current.label : "Home"} onBack={() => setSelected(null)} onChanged={() => setTick((t) => t + 1)} />
          ) : current ? (
            <div className="mx-auto flex max-w-6xl flex-col gap-7 px-10 py-10">
              <div className="flex flex-wrap items-end justify-between gap-4">
                <div>
                  <h1 className="font-display text-[2.25rem] leading-tight text-navy dark:text-text-primary">{current.label}</h1>
                  <p className="mt-1 text-body-regular text-text-secondary">{current.hint}</p>
                </div>
                <div className="flex items-center gap-2">
                  <div className="w-72"><SearchField aria-label="Search cases" placeholder="Search name or ID" value={search} onChange={setSearch} /></div>
                  <a href="/api/reviewed_decisions.jsonl" download="reviewed_decisions.jsonl" className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-separator-border bg-background-primary-default px-3 text-body-2-medium text-text-secondary hover:text-text-primary"><RiDownloadLine className="size-4" />Export</a>
                </div>
              </div>
              <QueueTable rows={visible} onOpen={setSelected} />
            </div>
          ) : (
            summary && <Overview summary={summary} counts={counts} tick={tick} onOpen={(k) => setQueue(k)} reviewer={reviewer} />
          )}
        </main>
      </div>

      {record && (
        <Modal isOpen onOpenChange={(o) => !o && setRecord(null)} isDismissable size="lg">
          <ModalDialog aria-label={record.id}>
            <ModalHeader title={record.id} description={record.kind.replace("_", " ")} />
            <ModalBody>
              <dl className="grid grid-cols-[9rem_1fr] gap-x-4 gap-y-2.5">
                {Object.entries(record.row).filter(([, v]) => v !== null && v !== "" && !(Array.isArray(v) && !v.length)).map(([k, v]) => (
                  <div key={k} className="contents">
                    <dt className="text-caption-1-medium text-text-tertiary">{k.replace(/_/g, " ")}</dt>
                    <dd className="text-body-2-regular whitespace-pre-wrap break-words text-text-primary">{Array.isArray(v) ? v.join("; ") : typeof v === "object" ? JSON.stringify(v) : String(v)}</dd>
                  </div>
                ))}
              </dl>
            </ModalBody>
          </ModalDialog>
        </Modal>
      )}

      <div className="pointer-events-none fixed top-4 right-4 z-50 flex w-96 flex-col gap-2">
        {toasts.map((t) => (
          <div key={t.id} className="pointer-events-auto"><Notification title={t.t} description={t.d} status={t.ok ? "success" : "error"} dismissible onDismiss={() => setToasts((x) => x.filter((y) => y.id !== t.id))} /></div>
        ))}
      </div>
    </AppCtx.Provider>
  );
}
