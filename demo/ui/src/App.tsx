import { useCallback, useEffect, useMemo, useState } from "react";
import {
  RiScales3Line, RiHome5Line, RiInboxLine, RiUserFollowLine, RiFlaskLine, RiAlertLine, RiCheckboxCircleLine,
  RiListCheck2, RiMoonLine, RiSunLine, RiDownloadLine, RiLogoutBoxRLine,
} from "@remixicon/react";
import { Button } from "@/components/base/buttons/button";
import { Switch } from "@/components/base/switch/switch";
import { SearchField } from "@/components/base/search-field/search-field";
import { Spinner } from "@/components/base/spinner/spinner";
import { Avatar } from "@/components/base/avatar/avatar";
import { Modal, ModalBody, ModalDialog, ModalHeader, ModalFooter } from "@/components/base/modal/modal";
import { Select, SelectItem } from "@/components/base/select/select";
import { Input } from "@/components/base/input/input";
import { Notification } from "@/components/base/notification/notification";
import { cx } from "@/utils/cx";
import { api, type Bucket, type CaseRow, type Summary } from "./api";
import { AppCtx, BUCKET, SYS, StatusChip, type Reviewer } from "./ui";
import Overview from "./Overview";
import CaseView from "./CaseView";

export type QueueKey = "overview" | "decide" | "approve" | "qa" | "escalated" | "closed" | "all";
const QUEUES: { key: QueueKey; label: string; icon: typeof RiInboxLine; buckets: Bucket[] | null; qa?: boolean; hint: string }[] = [
  { key: "decide", label: "To decide", icon: RiInboxLine, buckets: ["needs_decision", "returned", "proposed_match"], hint: "Cases the engine could not settle, and proposed matches." },
  { key: "approve", label: "To approve", icon: RiUserFollowLine, buckets: ["pending_approval"], hint: "A colleague decided; a second person must approve." },
  { key: "qa", label: "QA sample", icon: RiFlaskLine, buckets: ["proposed_clear"], qa: true, hint: "1 in 10 engine clearances, for a human spot-check." },
  { key: "escalated", label: "Escalated", icon: RiAlertLine, buckets: ["escalated"], hint: "Waiting on more information." },
  { key: "closed", label: "Closed", icon: RiCheckboxCircleLine, buckets: ["done"], hint: "Decided and approved by two people." },
  { key: "all", label: "All hits", icon: RiListCheck2, buckets: null, hint: "Every hit, including engine clearances." },
];

function load<T>(k: string, d: T): T { try { const v = localStorage.getItem(k); return v ? (JSON.parse(v) as T) : d; } catch { return d; } }
function save(k: string, v: unknown) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* ignore */ } }

function SignIn({ onDone }: { onDone: (r: Reviewer) => void }) {
  const [name, setName] = useState("");
  const [role, setRole] = useState<Reviewer["role"]>("analyst");
  return (
    <Modal isOpen isDismissable={false} size="sm">
      <ModalDialog aria-label="Sign in">
        <ModalHeader title="Sign in to review" description="Every decision is recorded under your name in an audit log that cannot be edited." showCloseButton={false} />
        <ModalBody>
          <div className="flex flex-col gap-4">
            <Input label="Your name" placeholder="e.g. Alex Morgan" value={name} onChange={setName} autoFocus />
            <Select label="Role" selectedKey={role} onSelectionChange={(k) => setRole(k as Reviewer["role"])}>
              <SelectItem id="analyst">Analyst: makes decisions</SelectItem>
              <SelectItem id="checker">Checker: approves decisions</SelectItem>
              <SelectItem id="qa">QA reviewer</SelectItem>
            </Select>
          </div>
        </ModalBody>
        <ModalFooter>
          <Button variant="primary" disabled={name.trim().length < 2} onClick={() => onDone({ name: name.trim(), role })}>Start reviewing</Button>
        </ModalFooter>
      </ModalDialog>
    </Modal>
  );
}

export default function App() {
  const [ready, setReady] = useState<string | true>("connecting");
  const [summary, setSummary] = useState<Summary | null>(null);
  const [rows, setRows] = useState<CaseRow[]>([]);
  const [queue, setQueueState] = useState<QueueKey>(() => load("cr-queue2", "overview"));
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [reviewer, setReviewerState] = useState<Reviewer | null>(() => load("cr-reviewer2", null));
  const [blind, setBlindState] = useState<boolean>(() => load("cr-blind2", false));
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"));
  const [tick, setTick] = useState(0);
  const [record, setRecord] = useState<{ id: string; kind: string; row: Record<string, unknown> } | null>(null);
  const [toasts, setToasts] = useState<{ id: number; t: string; d?: string; ok: boolean }[]>([]);

  const setQueue = (q: QueueKey) => { setQueueState(q); save("cr-queue2", q); setSelected(null); };
  const setReviewer = (r: Reviewer | null) => { setReviewerState(r); save("cr-reviewer2", r); };
  const setBlind = (b: boolean) => { setBlindState(b); save("cr-blind2", b); };
  const toggleDark = () => { const d = !dark; setDark(d); document.documentElement.classList.toggle("dark", d); save("cr-dark", d ? 1 : 0); try { localStorage.setItem("cr-dark", d ? "1" : "0"); } catch { /* */ } };
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
    return <div className="flex h-full flex-col items-center justify-center gap-3"><Spinner size="lg" /><p className="text-body-regular text-text-secondary">Engine: {ready}...</p></div>;
  }

  return (
    <AppCtx.Provider value={{ openRecord, reviewer, blind, toast }}>
      {!reviewer && <SignIn onDone={setReviewer} />}
      <div className="flex h-full min-h-0">
        {/* Navigation rail */}
        <nav className="flex w-60 shrink-0 flex-col border-r border-separator-border bg-background-primary-default">
          <button type="button" onClick={() => setQueue("overview")} className="flex items-center gap-3 px-5 py-5 text-left">
            <span className="flex size-9 items-center justify-center rounded-lg bg-accent-600 text-white"><RiScales3Line size={20} /></span>
            <span><span className="block text-headline-bold text-text-primary">Alibi</span><span className="block text-caption-1-regular text-text-tertiary">Sanctions case review</span></span>
          </button>
          <div className="flex flex-col gap-0.5 px-3">
            <NavItem active={queue === "overview"} icon={RiHome5Line} label="Overview" onClick={() => setQueue("overview")} />
            <p className="mt-4 mb-1 px-3 text-caption-1-semibold text-text-tertiary uppercase">Work queues</p>
            {QUEUES.map((q) => <NavItem key={q.key} active={queue === q.key} icon={q.icon} label={q.label} count={counts[q.key]} onClick={() => setQueue(q.key)} />)}
          </div>
          <div className="mt-auto flex flex-col gap-3 border-t border-separator-border p-4">
            <Switch isSelected={blind} onChange={setBlind} size="sm">Blind review</Switch>
            <div className="flex gap-2">
              <Button size="small" variant="secondary" leadingIcon={dark ? RiSunLine : RiMoonLine} onClick={toggleDark}>{dark ? "Light" : "Dark"}</Button>
              <a href="/api/reviewed_decisions.jsonl" download="reviewed_decisions.jsonl" className="inline-flex items-center gap-1 rounded-lg border border-separator-border px-2.5 py-1 text-caption-1-medium text-text-secondary hover:text-text-primary"><RiDownloadLine size={14} />Export</a>
            </div>
            {reviewer && (
              <div className="flex items-center gap-2">
                <Avatar size="sm" initials={reviewer.name.slice(0, 1).toUpperCase()} />
                <div className="min-w-0 flex-1"><p className="truncate text-body-2-semibold text-text-primary">{reviewer.name}</p><p className="text-caption-1-regular text-text-tertiary capitalize">{reviewer.role}</p></div>
                <Button size="xs" variant="ghost" iconOnly leadingIcon={RiLogoutBoxRLine} aria-label="Switch reviewer" onClick={() => setReviewer(null)} />
              </div>
            )}
          </div>
        </nav>

        {/* Case list (hidden while a case is open, like an inbox) */}
        {current && !selected && (
          <aside className="flex w-[22rem] shrink-0 flex-col border-r border-separator-border bg-background-primary-default">
            <div className="flex flex-col gap-2 border-b border-separator-border p-4">
              <h2 className="text-title-3-semibold text-text-primary">{current.label} <span className="text-text-tertiary">{counts[current.key]}</span></h2>
              <p className="text-caption-1-regular text-text-secondary">{current.hint}</p>
              <SearchField aria-label="Search cases" placeholder="Search name or ID" value={search} onChange={setSearch} />
            </div>
            <ul className="min-h-0 flex-1 overflow-y-auto">
              {visible.slice(0, 400).map((r) => (
                <li key={r.hit_id}>
                  <button type="button" onClick={() => setSelected(r.hit_id)}
                    className={cx("flex w-full flex-col gap-1 border-b border-separator-border px-4 py-3 text-left hover:bg-background-secondary-default",
                      selected === r.hit_id && "bg-background-secondary-default shadow-[inset_3px_0_0_var(--color-accent-500)]")}>
                    <span className="flex items-center justify-between gap-2">
                      <span className="truncate text-body-semibold text-text-primary">{r.hit_name}</span>
                      <StatusChip color={BUCKET[r.bucket].color}>{BUCKET[r.bucket].label}</StatusChip>
                    </span>
                    <span className="truncate text-caption-1-regular text-text-secondary">Screened as {r.screened_name || "unknown"}</span>
                    {!blind && !r.human && <span className="text-caption-1-regular text-text-tertiary">Engine: {SYS[r.system.decision].label} · {r.listing || "watchlist"}</span>}
                    {r.human?.decision && <span className="text-caption-1-regular text-text-tertiary">{r.human.maker} chose {r.human.decision.toLowerCase()}</span>}
                  </button>
                </li>
              ))}
              {!visible.length && <li className="p-8 text-center text-body-regular text-text-tertiary">Nothing here.</li>}
            </ul>
          </aside>
        )}

        {/* Main */}
        <main className="min-w-0 flex-1 overflow-y-auto">
          {selected ? (
            <CaseView key={selected + tick} hitId={selected} backLabel={current ? current.label : "Overview"} onBack={() => setSelected(null)} onChanged={() => setTick((t) => t + 1)} />
          ) : current ? (
            <div className="flex h-full items-center justify-center p-10 text-center">
              <div><p className="text-title-3-semibold text-text-primary">Pick a case</p><p className="mt-1 text-body-regular text-text-secondary">Choose a case from the list to see the evidence and decide.</p></div>
            </div>
          ) : (
            summary && <Overview summary={summary} counts={counts} tick={tick} onOpen={(k) => setQueue(k)} />
          )}
        </main>
      </div>

      {record && (
        <Modal isOpen onOpenChange={(o) => !o && setRecord(null)} isDismissable size="lg">
          <ModalDialog aria-label={record.id}>
            <ModalHeader title={record.id} description={record.kind.replace("_", " ")} />
            <ModalBody>
              <dl className="grid grid-cols-[10rem_1fr] gap-x-4 gap-y-2">
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

function NavItem({ active, icon: Icon, label, count, onClick }: { active: boolean; icon: typeof RiInboxLine; label: string; count?: number; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick}
      className={cx("flex items-center gap-3 rounded-lg px-3 py-2 text-left text-body-2-medium",
        active ? "bg-background-secondary-default text-text-primary" : "text-text-secondary hover:bg-background-secondary-default hover:text-text-primary")}>
      <Icon size={18} className={active ? "text-accent-600" : ""} />
      <span className="flex-1">{label}</span>
      {count !== undefined && <span className="text-caption-1-semibold text-text-tertiary">{count}</span>}
    </button>
  );
}
