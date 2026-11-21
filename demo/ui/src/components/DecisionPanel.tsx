import { useEffect, useState } from "react";
import { Alert, Badge, Button, Card, Group, MultiSelect, SegmentedControl, Select, Stack, Text, Textarea } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconCheck, IconArrowBackUp, IconLock, IconUserCheck } from "@tabler/icons-react";
import { api, CaseDetail, HumanDecision, HUM_COLOR, humanize, SystemDecision } from "../api";
import { useApp } from "../shared";
import type { CourtState } from "./Court";

const SYS_TO_HUM: Record<SystemDecision, HumanDecision> = { DIFFERENT_ENTITY: "CLEAR", SAME_ENTITY: "CONFIRM", REVIEW: "ESCALATE" };

export default function DecisionPanel({ detail, codes, court, picked, onDone, onChoose }: {
  detail: CaseDetail; codes: Record<HumanDecision, string[]> | null; court: CourtState; picked: string[];
  onDone: () => void; onChoose: (d: HumanDecision | null) => void;
}) {
  const { reviewer } = useApp();
  const [decision, setDecision] = useState<HumanDecision | null>(null);
  const [code, setCode] = useState<string | null>(null);
  const [cited, setCited] = useState<string[]>(detail.decision.evidence.filter((e) => detail.records.some((r) => r.id === e)));
  const [rationale, setRationale] = useState("");
  const [busy, setBusy] = useState(false);
  const wf = detail.workflow;
  const maker = [...detail.history].reverse().find((h) => h.action === "DECIDE");

  useEffect(() => { onChoose(decision); }, [decision, onChoose]);
  useEffect(() => {
    if (!decision || !codes) return;
    const sys = detail.decision;
    setCode(SYS_TO_HUM[sys.decision] === decision && codes[decision].includes(sys.reason_code) ? sys.reason_code : codes[decision][0]);
  }, [decision, codes, detail.decision]);

  const send = async (body: Record<string, unknown>, ok: string) => {
    if (!reviewer) return;
    setBusy(true);
    try {
      const r = await api.review({ hit_id: detail.decision.hit_id, reviewer: reviewer.name, role: reviewer.role, ...body });
      notifications.show({ color: "teal", title: ok, message: `Case is now ${humanize(r.workflow)}. Logged under ${reviewer.name}.`, icon: <IconCheck size={16} /> });
      onDone();
    } catch (e) {
      notifications.show({ color: "red", title: "Not recorded", message: (e as Error).message });
    } finally { setBusy(false); }
  };

  const recordOpts = detail.records.map((r) => ({ value: r.id, label: `${r.id} · ${r.kind.replace("_", " ")}` }));

  if (wf === "done") {
    const checker = [...detail.history].reverse().find((h) => h.action === "APPROVE");
    return (
      <Card>
        <Group gap="xs" mb="xs"><IconLock size={16} /><Text fw={650}>Closed</Text></Group>
        <Text size="sm">{humanize(maker?.decision)} by <b>{maker?.reviewer}</b>, approved by <b>{checker?.reviewer}</b>.</Text>
        <Text size="xs" c="dimmed" mt="xs">Closed cases are read-only. The audit log keeps every step.</Text>
      </Card>
    );
  }

  if (wf === "pending_approval" && maker) {
    const same = reviewer && reviewer.name.toLowerCase() === maker.reviewer.toLowerCase();
    return (
      <Card style={{ borderColor: "var(--mantine-color-violet-filled)" }}>
        <Group gap="xs" mb="xs"><IconUserCheck size={18} /><Text fw={650}>Four-eyes check</Text></Group>
        <Text size="sm"><b>{maker.reviewer}</b> decided <Badge color={HUM_COLOR[maker.decision as HumanDecision]}>{humanize(maker.decision)}</Badge></Text>
        <Text size="xs" c="dimmed" mt={4}>Reason: {humanize(maker.reason_code)} · cites {maker.record_ids.join(", ") || "nothing"}</Text>
        <Text size="sm" mt="xs" className="prewrap">"{maker.rationale}"</Text>
        {same ? (
          <Alert mt="md" color="orange" variant="light">You made this decision, so a different person must approve it.</Alert>
        ) : (
          <Stack mt="md" gap="xs">
            <Textarea label="Checker's note" placeholder="Why you approve, or what must be fixed" autosize minRows={3} value={rationale} onChange={(e) => setRationale(e.currentTarget.value)} />
            <Group grow>
              <Button color="teal" leftSection={<IconCheck size={16} />} loading={busy} disabled={rationale.trim().length < 10}
                      onClick={() => send({ action: "APPROVE", rationale }, "Approved")}>Approve</Button>
              <Button color="orange" variant="light" leftSection={<IconArrowBackUp size={16} />} loading={busy} disabled={rationale.trim().length < 10}
                      onClick={() => send({ action: "RETURN", rationale }, "Returned to the analyst")}>Return</Button>
            </Group>
          </Stack>
        )}
      </Card>
    );
  }

  const adj = court.adjudicator;
  return (
    <Card style={{ borderColor: "var(--mantine-primary-color-filled)" }}>
      <Text fw={650} mb={4}>Your decision</Text>
      <Text size="xs" c="dimmed" mb="sm">{wf === "returned" ? "A checker returned this case: see the audit trail, then decide again." : "You make the final call. A different reviewer will approve it."}</Text>
      <Stack gap="sm">
        <SegmentedControl fullWidth value={decision || ""} onChange={(v) => setDecision(v as HumanDecision)}
          data={[{ value: "CLEAR", label: "Clear" }, { value: "CONFIRM", label: "Match" }, { value: "ESCALATE", label: "Escalate" }]}
          color={decision ? HUM_COLOR[decision] : undefined} />
        {decision && (
          <>
            <Select label="Reason code (SOP)" value={code} onChange={setCode} allowDeselect={false}
                    data={(codes?.[decision] || []).map((c) => ({ value: c, label: humanize(c) }))} />
            <MultiSelect label="Records you rely on" placeholder={decision === "ESCALATE" ? "optional" : "at least one"} data={recordOpts}
                         value={cited} onChange={setCited} searchable clearable maxDropdownHeight={240} />
            {picked.length > 0 && (
              <Button size="xs" variant="subtle" onClick={() => setCited(Array.from(new Set([...cited, ...picked])))}>Add the {picked.length} records given to the court</Button>
            )}
            <Textarea label="Rationale" placeholder="The facts that decide it, in your own words" autosize minRows={4} value={rationale}
                      onChange={(e) => setRationale(e.currentTarget.value)} />
            {adj?.summary && (
              <Button size="xs" variant="subtle" onClick={() => setRationale((r) => (r ? r + "\n\n" : "") + "Adjudicator (AI, advisory): " + adj.summary)}>Insert the adjudicator's summary</Button>
            )}
            <Button size="md" color={HUM_COLOR[decision]} loading={busy}
                    disabled={!reviewer || !code || rationale.trim().length < 10 || (decision !== "ESCALATE" && !cited.length)}
                    onClick={() => send({ action: "DECIDE", decision, reason_code: code, record_ids: cited, rationale, court: court.adjudicator ? court : undefined },
                                       decision === "ESCALATE" ? "Escalated" : "Sent for approval")}>
              {decision === "ESCALATE" ? "Escalate case" : `Submit "${humanize(decision)}" for approval`}
            </Button>
          </>
        )}
      </Stack>
    </Card>
  );
}
