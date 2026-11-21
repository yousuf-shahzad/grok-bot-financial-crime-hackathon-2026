import { useCallback, useEffect, useState } from "react";
import {
  Alert, Anchor, Badge, Button, Card, Grid, Group, List, Loader, Stack, Table, Text, ThemeIcon, Timeline, Title, Tooltip,
} from "@mantine/core";
import {
  IconCheck, IconX, IconQuestionMark, IconRobot, IconEyeOff, IconFileText, IconFlask, IconHistory, IconBulb,
} from "@tabler/icons-react";
import { api, BUCKET_COLOR, BUCKET_LABEL, CaseDetail, CompRow, HumanDecision, HUM_COLOR, humanize, SYS_COLOR, SYS_LABEL } from "../api";
import { IdChip, useApp } from "../shared";
import Court, { CourtState } from "./Court";
import DecisionPanel from "./DecisionPanel";

const STATUS = {
  agree: { color: "red", icon: <IconCheck size={14} />, label: "Agrees: points to the same person" },
  contradict: { color: "teal", icon: <IconX size={14} />, label: "Contradicts: points to a different person" },
  unknown: { color: "gray", icon: <IconQuestionMark size={14} />, label: "Unknown: cannot be compared" },
};

function Facts({ facts }: { facts: (CompRow["customer"][number] | string)[] }) {
  if (!facts.length) return <Text size="sm" c="dimmed">unknown</Text>;
  return (
    <Stack gap={2}>
      {facts.slice(0, 3).map((f, i) => typeof f === "string" ? <Text key={i} size="sm">{f}</Text> : (
        <Group key={i} gap={6} wrap="nowrap" align="center">
          <Text size="sm" lineClamp={1} title={f.value} style={{ minWidth: 0 }}>{f.value}</Text>
          {f.kind && <Text size="xs" c="dimmed" style={{ flexShrink: 0 }}>{f.kind.replace("_", " ")}</Text>}
          <IdChip id={f.source} />
        </Group>
      ))}
      {facts.length > 3 && <Text size="xs" c="dimmed">+{facts.length - 3} more</Text>}
    </Stack>
  );
}

export default function CaseView({ hitId, onDecided }: { hitId: string; onDecided: () => void }) {
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
  const onChoose = useCallback((v: HumanDecision | null) => setChosen(v), []);

  if (err) return <Alert color="red">{err}</Alert>;
  if (!d) return <Group><Loader size="sm" /><Text c="dimmed">Loading case...</Text></Group>;

  const sys = d.decision;
  const hidden = blind && !chosen && !["pending_approval", "done"].includes(d.workflow);
  const missing = d.profile.missing || [];

  return (
    <Stack gap="lg" maw={1400}>
      <Group justify="space-between" align="flex-start">
        <div>
          <Group gap="xs"><Title order={2}>{d.profile.names[0]?.value || hitId}</Title>
            <Badge size="lg" variant="light" color={BUCKET_COLOR[d.workflow]}>{BUCKET_LABEL[d.workflow]}</Badge>
            {d.qa_sample && sys.decision === "DIFFERENT_ENTITY" && <Badge size="lg" variant="light" color="blue" leftSection={<IconFlask size={12} />}>QA sample</Badge>}
          </Group>
          <Text c="dimmed" size="sm">
            {d.profile.listing_kind ? humanize(d.profile.listing_kind) : "Watchlist profile"} · hit <IdChip id={hitId} /> · alert <IdChip id={sys.alert_id} /> · screened as <b>{String(d.alert.customer_name || "?")}</b>
            {d.alert.dob ? `, born ${String(d.alert.dob)}` : ""}{d.alert.country ? `, ${String(d.alert.country)}` : ""}
          </Text>
        </div>
        <Button variant="default" leftSection={<IconFileText size={16} />} component="a" href={`/api/report/${hitId}.md`} target="_blank">Case report</Button>
      </Group>

      <Grid gutter="lg">
        <Grid.Col span={{ base: 12, lg: 8 }}>
          <Stack gap="lg">
            <Card>
              <Group justify="space-between" mb="xs">
                <Text fw={650}>Engine recommendation</Text>
                {d.crossexam.downgraded && <Badge color="violet" variant="light" leftSection={<IconRobot size={12} />}>Sent back by Grok</Badge>}
              </Group>
              {hidden ? (
                <Alert variant="light" color="gray" icon={<IconEyeOff size={16} />}>
                  Blind review is on: choose your own decision on the right first, then the engine's view appears. This guards against anchoring on the machine.
                </Alert>
              ) : (
                <Stack gap="xs">
                  <Group gap="xs">
                    <Badge size="lg" color={SYS_COLOR[sys.decision]}>{SYS_LABEL[sys.decision]}</Badge>
                    <Badge size="lg" variant="light" color="gray" tt="none">{humanize(sys.reason_code)}</Badge>
                    {sys.customer_record_id && <Text size="sm" c="dimmed">customer {sys.customer_record_id === "AMBIGUOUS" ? "ambiguous (several people fit)" : ""}</Text>}
                    {sys.customer_record_id && sys.customer_record_id !== "AMBIGUOUS" && <IdChip id={sys.customer_record_id} />}
                  </Group>
                  <Text size="sm">{sys.reason}</Text>
                  {sys.evidence.length > 0 && <Group gap={4}><Text size="xs" c="dimmed">Relies on</Text>{sys.evidence.map((e) => <IdChip key={e} id={e} />)}</Group>}
                  {d.crossexam.rules_decision && (
                    <Text size="xs" c="violet">The rules wanted to clear this ({humanize(d.crossexam.rules_decision.reason_code)}); Grok's second read found a fact that blocks it.</Text>
                  )}
                  {d.label && (
                    <Text size="xs" c={d.label.decision === sys.decision ? "teal" : "red"}>
                      Practice label: {SYS_LABEL[d.label.decision]} ({d.label.reason_codes}) {d.label.decision === sys.decision ? "agrees" : "differs"}
                    </Text>
                  )}
                </Stack>
              )}
            </Card>

            <Card padding={0}>
              <Group justify="space-between" p="lg" pb="xs">
                <Text fw={650}>Customer vs watchlist hit</Text>
                <Group gap="xs">{Object.entries(STATUS).map(([k, s]) => (
                  <Tooltip key={k} label={s.label}><ThemeIcon size="sm" radius="xl" variant="light" color={s.color}>{s.icon}</ThemeIcon></Tooltip>
                ))}</Group>
              </Group>
              <Table verticalSpacing="sm" horizontalSpacing="lg" highlightOnHover layout="fixed">
                <Table.Thead>
                  <Table.Tr><Table.Th w={130}>Field</Table.Th><Table.Th>Customer (our records)</Table.Th><Table.Th>Watchlist hit</Table.Th><Table.Th w={120}>Verdict</Table.Th></Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {d.comparison.map((r) => (
                    <Table.Tr key={r.field}>
                      <Table.Td><Text size="sm" fw={600}>{r.field}</Text></Table.Td>
                      <Table.Td><Facts facts={r.customer} /></Table.Td>
                      <Table.Td><Facts facts={r.hit} /></Table.Td>
                      <Table.Td>
                        <Tooltip label={r.note || STATUS[r.status].label} multiline w={260} withArrow>
                          <Badge variant="light" color={STATUS[r.status].color} leftSection={STATUS[r.status].icon}>
                            {r.status === "agree" ? "Same" : r.status === "contradict" ? "Different" : "Unknown"}
                          </Badge>
                        </Tooltip>
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
              {d.resolution && <Text size="xs" c="dimmed" px="lg" py="sm">How we found the customer: {d.resolution.note}</Text>}
            </Card>

            {missing.length > 0 && d.workflow !== "done" && (
              <Alert variant="light" color="yellow" icon={<IconBulb size={16} />} title="What would settle this">
                <List size="sm" spacing={2}>{missing.map((m, i) => <List.Item key={i}>{humanize(m)}: request it from the customer or a provider (RFI).</List.Item>)}</List>
              </Alert>
            )}

            <Court detail={d} picked={picked} setPicked={setPicked} court={court} setCourt={setCourt} />

            <Card>
              <Group gap="xs" mb="sm"><IconHistory size={18} /><Text fw={650}>Audit trail</Text><Badge size="xs" variant="light" color="gray">append-only</Badge></Group>
              {d.history.length === 0 ? <Text size="sm" c="dimmed">No human action yet.</Text> : (
                <Timeline bulletSize={22} lineWidth={2} active={d.history.length}>
                  {d.history.map((h) => (
                    <Timeline.Item key={h.id} title={<Group gap="xs"><Text size="sm" fw={600}>{h.action === "DECIDE" ? humanize(h.decision) : humanize(h.action)}</Text>
                      <Text size="xs" c="dimmed">by {h.reviewer} ({h.role}) · {h.created_at.replace("T", " ")}</Text>
                      {h.action === "DECIDE" && h.agreed_with_system === 0 && <Badge size="xs" color="orange" variant="light">overrode engine</Badge>}</Group>}
                      color={h.action === "RETURN" ? "orange" : h.action === "APPROVE" ? "teal" : h.decision ? HUM_COLOR[h.decision] : "gray"}>
                      {h.reason_code && <Text size="xs" c="dimmed">{humanize(h.reason_code)}{h.record_ids.length ? " · cites " + h.record_ids.join(", ") : ""}</Text>}
                      <Text size="sm" className="prewrap">{h.rationale}</Text>
                    </Timeline.Item>
                  ))}
                </Timeline>
              )}
            </Card>
          </Stack>
        </Grid.Col>

        <Grid.Col span={{ base: 12, lg: 4 }}>
          <div className="sticky-col">
            <DecisionPanel detail={d} codes={codes} court={court} picked={picked} onChoose={onChoose}
                           onDone={() => { load(); onDecided(); }} />
            <Text size="xs" c="dimmed" mt="sm" ta="center">
              Every action is logged with your name and time. <Anchor size="xs" href="/api/reviewed_decisions.jsonl">Export decisions</Anchor>
            </Text>
          </div>
        </Grid.Col>
      </Grid>
    </Stack>
  );
}
