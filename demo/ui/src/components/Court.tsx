import { useMemo, useState } from "react";
import {
  Accordion, Alert, Badge, Button, Card, Checkbox, Group, List, Loader, SimpleGrid, Stack, Tabs, Text, ThemeIcon, Tooltip,
} from "@mantine/core";
import { IconGavel, IconShieldX, IconShieldCheck, IconRobot, IconSparkles, IconAlertTriangle } from "@tabler/icons-react";
import { api, Arg, CaseDetail, CourtOut, HUM_COLOR, humanize } from "../api";
import { IdChip } from "../shared";

export type CourtState = { prosecution?: CourtOut; defence?: CourtOut; adjudicator?: CourtOut };

function RuleArgs({ args, side }: { args: Arg[]; side: "pros" | "def" }) {
  if (!args.length) return <Text size="sm" c="dimmed">Nothing on this side from the rules.</Text>;
  return (
    <Stack gap="xs">
      {args.map((a, i) => (
        <Group key={i} gap="sm" wrap="nowrap" align="flex-start" opacity={side === "def" && !a.holds ? 0.6 : 1}>
          <ThemeIcon size="sm" radius="xl" variant={side === "pros" || a.holds ? "filled" : "light"}
                     color={side === "pros" ? "red" : a.holds ? "teal" : "gray"}>
            {side === "pros" ? <IconShieldX size={12} /> : <IconShieldCheck size={12} />}
          </ThemeIcon>
          <div style={{ minWidth: 0 }}>
            <Text size="sm" fw={600}>{a.what || a.rule}{side === "def" && <Text span size="xs" c={a.holds ? "teal" : "dimmed"} fw={700} ml={6}>{a.holds ? "HOLDS" : "does not hold"}</Text>}</Text>
            <Text size="xs" c="dimmed">{a.detail}</Text>
            {a.note && <Text size="xs" c="orange">{a.note}</Text>}
            {a.sources && <Group gap={4} mt={4}>{a.sources.map((s) => <IdChip key={s} id={s} />)}</Group>}
          </div>
        </Group>
      ))}
    </Stack>
  );
}

function AiArg({ out }: { out?: CourtOut }) {
  if (!out) return null;
  if (out.error) return <Alert color="red" variant="light" icon={<IconAlertTriangle size={16} />}>{out.error}</Alert>;
  return (
    <Stack gap="xs">
      {out.position && <Text size="sm" fw={600}>{out.position}</Text>}
      {(out.points || []).map((p, i) => (
        <div key={i}>
          <Text size="sm">• {p.claim}</Text>
          <Group gap={4} ml="md" mt={2}>{p.evidence_ids.map((e) => <IdChip key={e} id={e} />)}</Group>
        </div>
      ))}
      {!!out.gaps?.length && <Text size="xs" c="orange">Unknown: {out.gaps.join("; ")}</Text>}
    </Stack>
  );
}

export default function Court({ detail, picked, setPicked, court, setCourt }: {
  detail: CaseDetail; picked: string[]; setPicked: (v: string[]) => void; court: CourtState; setCourt: (c: CourtState) => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const trial = detail.court[0];
  const groups = useMemo(() => {
    const g: Record<string, typeof detail.records> = {};
    for (const r of detail.records) (g[r.group] ||= []).push(r);
    return g;
  }, [detail.records]);

  const call = async (role: "prosecution" | "defence" | "adjudicator", prior?: CourtState) => {
    const body: Record<string, unknown> = { hit_id: detail.decision.hit_id, role, record_ids: picked };
    if (role === "adjudicator") body.prior = { prosecution: prior?.prosecution || {}, defence: prior?.defence || {} };
    try { return await api.court(body); } catch (e) { return { error: (e as Error).message } as CourtOut; }
  };

  const convene = async () => {
    setBusy("Prosecution and defence are arguing...");
    const [p, d] = await Promise.all([call("prosecution"), call("defence")]);
    const next = { prosecution: p, defence: d };
    setCourt(next);
    setBusy("The adjudicator is weighing both sides...");
    const a = await call("adjudicator", next);
    setCourt({ ...next, adjudicator: a });
    setBusy(null);
  };

  const adj = court.adjudicator;
  return (
    <Card>
      <Group justify="space-between" mb="sm">
        <Group gap="xs"><IconGavel size={18} /><Text fw={650}>The court</Text></Group>
        <Badge variant="light" color="gray">Rules first · AI on request only</Badge>
      </Group>

      <Tabs defaultValue="rules" keepMounted={false}>
        <Tabs.List>
          <Tabs.Tab value="rules">Rules engine</Tabs.Tab>
          <Tabs.Tab value="ai" leftSection={<IconRobot size={14} />}>AI court</Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="rules" pt="md">
          {!trial ? <Text size="sm" c="dimmed">No customer was found for this alert, so there is nothing to compare.</Text> : (
            <SimpleGrid cols={{ base: 1, md: 2 }}>
              <Card bg="var(--mantine-color-red-light)" withBorder={false} padding="md">
                <Text size="xs" fw={700} tt="uppercase" c="red" mb="xs">Prosecution: it IS the customer</Text>
                <RuleArgs args={trial.prosecution} side="pros" />
              </Card>
              <Card bg="var(--mantine-color-teal-light)" withBorder={false} padding="md">
                <Text size="xs" fw={700} tt="uppercase" c="teal" mb="xs">Defence: it is NOT the customer</Text>
                <RuleArgs args={trial.defence} side="def" />
              </Card>
            </SimpleGrid>
          )}
        </Tabs.Panel>

        <Tabs.Panel value="ai" pt="md">
          {!detail.court_available && (
            <Alert color="gray" variant="light" mb="md">The AI court needs an LLM key (XAI_API_KEY or OPENROUTER_API_KEY in .env). The rules view still works.</Alert>
          )}
          <Text size="sm" mb="xs">Choose the records the agents may read and cite. Nothing else is sent.</Text>
          <Accordion variant="contained" multiple defaultValue={["Customer records", "Watchlist hit"]} mb="md">
            {Object.entries(groups).map(([g, recs]) => (
              <Accordion.Item key={g} value={g}>
                <Accordion.Control>
                  <Group gap="xs"><Text size="sm" fw={600}>{g}</Text>
                    <Badge size="xs" variant="light">{recs.filter((r) => picked.includes(r.id)).length}/{recs.length}</Badge></Group>
                </Accordion.Control>
                <Accordion.Panel>
                  <Stack gap="xs">
                    {recs.map((r) => (
                      <Checkbox key={r.id} checked={picked.includes(r.id)}
                        onChange={(e) => setPicked(e.currentTarget.checked ? [...picked, r.id] : picked.filter((x) => x !== r.id))}
                        label={<Group gap={6} wrap="nowrap" align="flex-start"><IdChip id={r.id} />
                          <Text size="xs" c="dimmed" lineClamp={2} className="prewrap">{r.text.replace(/\n/g, " · ")}</Text></Group>} />
                    ))}
                  </Stack>
                </Accordion.Panel>
              </Accordion.Item>
            ))}
          </Accordion>
          <Group>
            <Button leftSection={<IconSparkles size={16} />} onClick={convene} disabled={!detail.court_available || !!busy || !picked.length}
                    variant="gradient" gradient={{ from: "indigo", to: "violet" }}>Convene the court ({picked.length} records)</Button>
            {busy && <Group gap="xs"><Loader size="xs" /><Text size="sm" c="dimmed">{busy}</Text></Group>}
          </Group>

          {(court.prosecution || court.defence) && (
            <SimpleGrid cols={{ base: 1, md: 2 }} mt="md">
              <Card withBorder padding="md"><Text size="xs" fw={700} tt="uppercase" c="red" mb="xs">AI prosecution</Text><AiArg out={court.prosecution} /></Card>
              <Card withBorder padding="md"><Text size="xs" fw={700} tt="uppercase" c="teal" mb="xs">AI defence</Text><AiArg out={court.defence} /></Card>
            </SimpleGrid>
          )}
          {adj && (
            <Card withBorder mt="md" padding="md" style={{ borderColor: "var(--mantine-color-indigo-filled)" }}>
              <Group justify="space-between" mb="xs">
                <Group gap="xs"><IconGavel size={16} /><Text fw={700}>Adjudicator's summary</Text></Group>
                <Badge variant="outline" color="gray">AI-written · advisory, you decide</Badge>
              </Group>
              {adj.error ? <Alert color="red" variant="light">{adj.error}</Alert> : (
                <Stack gap="xs">
                  <Text size="sm">{adj.summary}</Text>
                  <Group gap="xs">
                    {adj.suggested_disposition && <Badge color={HUM_COLOR[adj.suggested_disposition]}>Suggests: {humanize(adj.suggested_disposition)}</Badge>}
                    {adj.confidence && <Tooltip label="The adjudicator's own confidence"><Badge variant="light">Confidence: {adj.confidence}</Badge></Tooltip>}
                    {adj.sop_rule && <Badge variant="light" color="gray" tt="none">SOP: {adj.sop_rule}</Badge>}
                  </Group>
                  {!!adj.what_would_settle?.length && (
                    <div><Text size="xs" fw={700} c="dimmed" tt="uppercase">What would settle it</Text>
                      <List size="sm" spacing={2}>{adj.what_would_settle.map((w, i) => <List.Item key={i}>{w}</List.Item>)}</List></div>
                  )}
                </Stack>
              )}
            </Card>
          )}
        </Tabs.Panel>
      </Tabs>
    </Card>
  );
}
