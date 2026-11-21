import { useEffect, useState } from "react";
import { Badge, Button, Card, Group, Progress, SimpleGrid, Stack, Text, ThemeIcon, Title, List } from "@mantine/core";
import { IconChecklist, IconScale, IconShieldCheck, IconUsers, IconRobot, IconFlask } from "@tabler/icons-react";
import { api, Mi, Summary } from "../api";
import type { QueueKey } from "../App";

function Stat({ label, value, sub, color, icon }: { label: string; value: string | number; sub?: string; color: string; icon: React.ReactNode }) {
  return (
    <Card>
      <Group justify="space-between" align="flex-start">
        <div>
          <Text size="xs" c="dimmed" tt="uppercase" fw={700}>{label}</Text>
          <Text fz={28} fw={700} lh={1.2}>{value}</Text>
          {sub && <Text size="xs" c="dimmed">{sub}</Text>}
        </div>
        <ThemeIcon variant="light" color={color} size="lg" radius="md">{icon}</ThemeIcon>
      </Group>
    </Card>
  );
}

export default function Overview({ summary, counts, tick, onOpenQueue }: {
  summary: Summary; counts: Record<QueueKey, number>; tick: number; onOpenQueue: (k: QueueKey) => void;
}) {
  const [mi, setMi] = useState<Mi | null>(null);
  useEffect(() => { api.mi().then(setMi).catch(() => {}); }, [tick]);
  const total = summary.hits || 1;
  const n = (d: string) => Object.values(summary.by_decision[d] || {}).reduce((a, b) => a + b, 0);
  const closed = counts.closed;
  return (
    <Stack gap="lg" maw={1200}>
      <div>
        <Title order={2}>Review overview</Title>
        <Text c="dimmed">The engine recommends. You decide, a second reviewer approves, and every step lands in an append-only audit log.</Text>
      </div>

      <SimpleGrid cols={{ base: 1, sm: 2, lg: 4 }}>
        <Stat label="To decide" value={counts.decide} sub="engine could not settle" color="yellow" icon={<IconChecklist size={18} />} />
        <Stat label="To approve" value={counts.approve} sub="four-eyes checks" color="violet" icon={<IconUsers size={18} />} />
        <Stat label="QA sample" value={counts.qa} sub="1 in 10 engine clears" color="blue" icon={<IconFlask size={18} />} />
        <Stat label="Closed" value={closed} sub={`${Math.round((100 * closed) / total)}% of ${summary.hits} hits`} color="gray" icon={<IconShieldCheck size={18} />} />
      </SimpleGrid>

      <SimpleGrid cols={{ base: 1, lg: 2 }}>
        <Card>
          <Group justify="space-between" mb="sm">
            <Text fw={650}>What the engine recommends</Text>
            <Badge variant="light">{summary.hits} hits · {summary.alerts} alerts</Badge>
          </Group>
          <Progress.Root size={22} radius="md">
            <Progress.Section value={(100 * n("DIFFERENT_ENTITY")) / total} color="teal"><Progress.Label>Clear {n("DIFFERENT_ENTITY")}</Progress.Label></Progress.Section>
            <Progress.Section value={(100 * n("REVIEW")) / total} color="yellow"><Progress.Label>Review {n("REVIEW")}</Progress.Label></Progress.Section>
            <Progress.Section value={(100 * n("SAME_ENTITY")) / total} color="red"><Progress.Label>Match {n("SAME_ENTITY")}</Progress.Label></Progress.Section>
          </Progress.Root>
          <Group mt="md" gap="xs">
            <Button size="xs" variant="light" color="yellow" onClick={() => onOpenQueue("decide")}>Open "to decide"</Button>
            <Button size="xs" variant="light" color="red" onClick={() => onOpenQueue("matches")}>Proposed matches ({counts.matches})</Button>
            <Button size="xs" variant="light" color="teal" onClick={() => onOpenQueue("clears")}>Proposed clears ({counts.clears})</Button>
          </Group>
          {summary.practice.n > 0 && (
            <Text size="sm" mt="md">
              Practice labels: <b>{summary.practice.right}/{summary.practice.n}</b> right, decision score <b>{summary.practice.score}%</b>,{" "}
              <Text span c={summary.practice.unsafe ? "red" : "teal"} fw={700}>{summary.practice.unsafe} unsafe clearances</Text>.
            </Text>
          )}
        </Card>

        <Card>
          <Text fw={650} mb="sm">Human review so far</Text>
          {mi && mi.decisions + mi.approvals + mi.returns > 0 ? (
            <SimpleGrid cols={2} spacing="xs">
              <Text size="sm">Decisions <b>{mi.decisions}</b></Text>
              <Text size="sm">Approvals <b>{mi.approvals}</b></Text>
              <Text size="sm">Returned <b>{mi.returns}</b></Text>
              <Text size="sm">Agreed with engine <b>{mi.agreement_rate ?? "-"}%</b></Text>
              <Text size="sm">Overrides <b>{mi.overrides}</b></Text>
              <Text size="sm">Audit rows <b>{mi.audit_rows}</b></Text>
              <Text size="sm" style={{ gridColumn: "1 / -1" }} c="dimmed">
                By reviewer: {Object.entries(mi.by_reviewer).map(([k, v]) => `${k} ${v}`).join(", ")}
              </Text>
            </SimpleGrid>
          ) : (
            <Text size="sm" c="dimmed">No human decisions yet. Pick a case from "To decide" to start.</Text>
          )}
        </Card>
      </SimpleGrid>

      <Card>
        <Group gap="xs" mb="xs"><IconScale size={18} /><Text fw={650}>How a case is decided</Text></Group>
        <List spacing={6} size="sm">
          <List.Item><b>Engine</b>: resolves who the customer is and who the listed person is, then applies the bank's SOP as code. It clears only on a named contradiction and confirms only on agreement. Everything else is left for you.</List.Item>
          <List.Item><b>Grok cross-examiner</b> <IconRobot size={12} />: re-reads the text behind every clearance and can only send it back to review, never clear anything{summary.crossexam_downgrades ? ` (sent back ${summary.crossexam_downgrades} this run)` : ""}.</List.Item>
          <List.Item><b>You</b>: compare customer and hit, optionally ask the AI court (prosecution, defence, adjudicator) to argue over records you choose, then decide with a reason code, cited records and a rationale.</List.Item>
          <List.Item><b>Checker</b>: a different person approves or returns your decision. The audit log cannot be edited or deleted.</List.Item>
        </List>
      </Card>
    </Stack>
  );
}
