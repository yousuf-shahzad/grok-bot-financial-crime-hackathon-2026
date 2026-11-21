// Types and calls for demo/app.py. Everything stays on 127.0.0.1.

export type SystemDecision = "DIFFERENT_ENTITY" | "SAME_ENTITY" | "REVIEW";
export type HumanDecision = "CLEAR" | "CONFIRM" | "ESCALATE";
export type Bucket =
  | "needs_decision" | "returned" | "pending_approval" | "proposed_match" | "proposed_clear" | "escalated" | "done";

export interface FactV { value: string; source?: string | null; kind?: string | null }

export interface CaseRow {
  hit_id: string; alert_id: string; hit_name: string; screened_name: string; entity_type: string;
  listing: string | null; system: { decision: SystemDecision; reason_code: string };
  bucket: Bucket; qa_sample: boolean; crossexamined: boolean; practice_truth?: SystemDecision;
  human: { decision: HumanDecision | null; maker: string; checker: string | null; at: string } | null;
}

export interface CasesResp { rows: CaseRow[]; total: number; counts: Record<string, number> }

export interface HistoryRow {
  id: number; hit_id: string; reviewer: string; role: string; action: "DECIDE" | "APPROVE" | "RETURN";
  decision: HumanDecision | null; reason_code: string | null; record_ids: string[]; rationale: string;
  system_decision: string; agreed_with_system: number | null; created_at: string; llm?: string;
}

export interface CompRow { field: string; customer: FactV[]; hit: (FactV | string)[]; status: "agree" | "contradict" | "unknown"; note: string | null }
export interface RecordOpt { id: string; kind: string; group: string; default: boolean; text: string }
export interface Arg { what?: string; rule?: string; detail: string; holds?: boolean; note?: string; sources?: string[] }

export interface CaseDetail {
  decision: { hit_id: string; alert_id: string; decision: SystemDecision; reason_code: string; customer_record_id: string | null; reason: string; evidence: string[] };
  alert: Record<string, unknown>;
  profile: { hit_id: string; names: FactV[]; births: string[]; countries: FactV[]; listing_kind: string; missing: string[]; entity_type: string;
             earliest_report: FactV | null; deceased: FactV | null };
  resolution: { people: { person_id: string; record_ids: string[] }[]; note: string } | null;
  court: { person_id: string; prosecution: Arg[]; defence: Arg[] }[];
  comparison: CompRow[]; records: RecordOpt[]; history: HistoryRow[]; workflow: Bucket; qa_sample: boolean;
  court_available: boolean; label?: { decision: SystemDecision; reason_codes: string } | null;
  crossexam: { provider: string; downgraded: boolean; rules_decision: { decision: string; reason_code: string; reason: string } | null };
  people?: { person_id: string; record_ids: string[]; name: string | null; dob: string | null; dob_source: string | null; countries: string[]; decision: SystemDecision; reason_code: string }[];
}

export interface CourtPoint { claim: string; evidence_ids: string[] }
export interface CourtOut {
  role?: string; error?: string; position?: string; points?: CourtPoint[]; gaps?: string[];
  summary?: string; suggested_disposition?: "CLEAR" | "CONFIRM" | "ESCALATE"; confidence?: string;
  what_would_settle?: string[]; sop_rule?: string;
}

export interface Summary {
  hits: number; alerts: number; seconds: number; llm: string; blindfold: boolean; crossexam_downgrades: number;
  by_decision: Record<string, Record<string, number>>;
  practice: { n: number; right: number; unsafe: number; cost: number; baseline: number; score: number | null };
}
export interface Mi {
  decisions: number; approvals: number; returns: number; agreement_rate: number | null; overrides: number;
  by_reviewer: Record<string, number>; buckets: Record<string, number>; audit_rows: number;
}

async function j<T>(r: Response): Promise<T> {
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error((body as { error?: string }).error || `HTTP ${r.status}`);
  return body as T;
}

export const api = {
  status: () => fetch("/api/status").then((r) => j<{ ready: boolean; status: string }>(r)),
  summary: () => fetch("/api/summary").then((r) => j<Summary>(r)),
  mi: () => fetch("/api/mi").then((r) => j<Mi>(r)),
  codes: () => fetch("/api/codes").then((r) => j<Record<HumanDecision, string[]>>(r)),
  cases: (p: Record<string, string>) => fetch("/api/cases?" + new URLSearchParams(p)).then((r) => j<CasesResp>(r)),
  case: (id: string) => fetch("/api/case/" + encodeURIComponent(id)).then((r) => j<CaseDetail>(r)),
  record: (id: string) => fetch("/api/record/" + encodeURIComponent(id)).then((r) => j<{ id: string; kind: string; row: Record<string, unknown> }>(r)),
  review: (body: Record<string, unknown>) =>
    fetch("/api/review", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
      .then((r) => j<{ ok: boolean; history: HistoryRow[]; workflow: Bucket }>(r)),
  court: (body: Record<string, unknown>) =>
    fetch("/api/court", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
      .then((r) => j<CourtOut>(r)),
};

export const SYS_LABEL: Record<SystemDecision, string> = { DIFFERENT_ENTITY: "Clear", SAME_ENTITY: "Match", REVIEW: "Review" };
export const SYS_COLOR: Record<SystemDecision, string> = { DIFFERENT_ENTITY: "teal", SAME_ENTITY: "red", REVIEW: "yellow" };
export const HUM_LABEL: Record<HumanDecision, string> = { CLEAR: "Clear (false positive)", CONFIRM: "Confirm match", ESCALATE: "Escalate" };
export const HUM_COLOR: Record<HumanDecision, string> = { CLEAR: "teal", CONFIRM: "red", ESCALATE: "yellow" };
export const BUCKET_LABEL: Record<Bucket, string> = {
  needs_decision: "Needs decision", returned: "Returned", pending_approval: "Awaiting approval",
  proposed_match: "Proposed match", proposed_clear: "Proposed clear", escalated: "Escalated", done: "Closed",
};
export const BUCKET_COLOR: Record<Bucket, string> = {
  needs_decision: "yellow", returned: "orange", pending_approval: "violet", proposed_match: "red",
  proposed_clear: "teal", escalated: "orange", done: "gray",
};
export const humanize = (s: string | null | undefined) => (s || "").toLowerCase().replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
