import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ActionIcon, AppShell, Badge, Box, Button, Center, Drawer, Group, Loader, Menu, Modal, ScrollArea, SegmentedControl,
  Stack, Switch, Table, Text, TextInput, ThemeIcon, Title, Tooltip, useMantineColorScheme, Avatar, Select, Code,
} from "@mantine/core";
import { useDisclosure, useLocalStorage } from "@mantine/hooks";
import {
  IconMoon, IconSun, IconScale, IconSearch, IconEyeOff, IconUserCircle, IconLogout, IconDownload, IconRobot,
} from "@tabler/icons-react";
import { api, CaseRow, Summary, Bucket } from "./api";
import { AppCtx, Reviewer } from "./shared";
import Queue from "./components/Queue";
import Overview from "./components/Overview";
import CaseView from "./components/CaseView";

export type QueueKey = "decide" | "approve" | "qa" | "matches" | "clears" | "escalated" | "closed" | "all";
export const QUEUES: { key: QueueKey; label: string; buckets: Bucket[] | null; qa?: boolean; hint: string }[] = [
  { key: "decide", label: "To decide", buckets: ["needs_decision", "returned"], hint: "The engine could not settle these: your call." },
  { key: "approve", label: "To approve", buckets: ["pending_approval"], hint: "Four-eyes: approve or return a colleague's decision." },
  { key: "qa", label: "QA sample", buckets: ["proposed_clear"], qa: true, hint: "1 in 10 engine clearances, for human spot-checks." },
  { key: "matches", label: "Proposed matches", buckets: ["proposed_match"], hint: "The engine thinks the hit is the customer." },
  { key: "clears", label: "Proposed clears", buckets: ["proposed_clear"], hint: "The engine found a named contradiction." },
  { key: "escalated", label: "Escalated", buckets: ["escalated"], hint: "Sent for more information or a second-line view." },
  { key: "closed", label: "Closed", buckets: ["done"], hint: "Decided and approved by two different people." },
  { key: "all", label: "All", buckets: null, hint: "Every hit." },
];

function SignIn({ onDone }: { onDone: (r: Reviewer) => void }) {
  const [name, setName] = useState("");
  const [role, setRole] = useState<string | null>("analyst");
  return (
    <Modal opened onClose={() => {}} withCloseButton={false} centered title={<Title order={4}>Sign in to Case Review</Title>}>
      <Stack>
        <Text size="sm" c="dimmed">Every decision is recorded in an append-only audit log under your name. In production this is where single sign-on plugs in.</Text>
        <TextInput label="Your name" placeholder="e.g. Alex Morgan" value={name} onChange={(e) => setName(e.currentTarget.value)} data-autofocus />
        <Select label="Role" value={role} onChange={setRole} allowDeselect={false}
                data={[{ value: "analyst", label: "Analyst (makes decisions)" }, { value: "checker", label: "Checker (approves decisions)" }, { value: "qa", label: "QA reviewer" }]} />
        <Button disabled={name.trim().length < 2} onClick={() => onDone({ name: name.trim(), role: (role as Reviewer["role"]) || "analyst" })}>Start reviewing</Button>
      </Stack>
    </Modal>
  );
}

export default function App() {
  const [ready, setReady] = useState<string | true>("connecting");
  const [summary, setSummary] = useState<Summary | null>(null);
  const [rows, setRows] = useState<CaseRow[]>([]);
  const [queue, setQueue] = useLocalStorage<QueueKey>({ key: "cr-queue", defaultValue: "decide" });
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [reviewer, setReviewer] = useLocalStorage<Reviewer | null>({ key: "cr-reviewer", defaultValue: null });
  const [blind, setBlind] = useLocalStorage<boolean>({ key: "cr-blind", defaultValue: false });
  const [tick, setTick] = useState(0);
  const [recordId, setRecordId] = useState<string | null>(null);
  const [record, setRecord] = useState<{ id: string; kind: string; row: Record<string, unknown> } | null>(null);
  const [drawerOpen, drawer] = useDisclosure(false);
  const { colorScheme, toggleColorScheme } = useMantineColorScheme();

  useEffect(() => {
    let stop = false;
    const poll = async () => {
      try {
        const s = await api.status();
        if (s.ready) { setReady(true); return; }
        setReady(s.status);
      } catch { setReady("waiting for the server"); }
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

  const refresh = useCallback(() => setTick((t) => t + 1), []);
  const openRecord = useCallback((id: string) => {
    setRecordId(id); setRecord(null); drawer.open();
    api.record(id).then(setRecord).catch(() => setRecord({ id, kind: "not found", row: {} }));
  }, [drawer]);

  const counts = useMemo(() => {
    const c: Record<QueueKey, number> = { decide: 0, approve: 0, qa: 0, matches: 0, clears: 0, escalated: 0, closed: 0, all: rows.length };
    for (const r of rows) {
      for (const q of QUEUES) {
        if (q.key === "all" || !q.buckets) continue;
        if (q.buckets.includes(r.bucket) && (!q.qa || r.qa_sample)) c[q.key] += 1;
      }
    }
    return c;
  }, [rows]);

  const visible = useMemo(() => {
    const q = QUEUES.find((x) => x.key === queue)!;
    const s = search.trim().toLowerCase();
    return rows.filter((r) => (!q.buckets || q.buckets.includes(r.bucket)) && (!q.qa || r.qa_sample)
      && (!s || `${r.hit_id} ${r.alert_id} ${r.hit_name} ${r.screened_name} ${r.system.reason_code}`.toLowerCase().includes(s)));
  }, [rows, queue, search]);

  if (ready !== true) {
    return <Center h="100vh"><Stack align="center" gap="xs"><Loader /><Text c="dimmed">Engine: {ready}...</Text></Stack></Center>;
  }

  return (
    <AppCtx.Provider value={{ openRecord, reviewer, blind, refresh }}>
      {!reviewer && <SignIn onDone={setReviewer} />}
      <AppShell header={{ height: 60 }} navbar={{ width: { base: 300, lg: 340 }, breakpoint: "sm" }} padding="lg">
        <AppShell.Header>
          <Group h="100%" px="md" justify="space-between" wrap="nowrap">
            <Group gap="sm" wrap="nowrap" style={{ cursor: "pointer" }} onClick={() => setSelected(null)}>
              <ThemeIcon size="lg" radius="md" variant="gradient" gradient={{ from: "indigo", to: "violet" }}><IconScale size={20} /></ThemeIcon>
              <Box>
                <Text fw={700} lh={1.1}>Alibi</Text>
                <Text size="xs" c="dimmed" lh={1.1}>Sanctions screening case review</Text>
              </Box>
            </Group>
            <Group gap="sm" wrap="nowrap">
              {summary && (
                <Tooltip label={summary.llm === "rules only (no LLM key)" ? "No LLM key: rules only" : "Grok re-reads the text behind every clearance and can only send it back to review"} withArrow>
                  <Badge variant="light" color={summary.llm.startsWith("rules") ? "gray" : "violet"} leftSection={<IconRobot size={12} />} visibleFrom="md">
                    {summary.llm.startsWith("rules") ? "Rules only" : "Grok cross-examiner on"}
                  </Badge>
                </Tooltip>
              )}
              {summary?.blindfold && <Badge color="orange" variant="filled">Demo: note parser off</Badge>}
              <Tooltip label="Hide the engine's recommendation until you have chosen (FCA good practice against anchoring)" withArrow multiline w={260}>
                <Switch checked={blind} onChange={(e) => setBlind(e.currentTarget.checked)} label="Blind review" thumbIcon={<IconEyeOff size={10} />} visibleFrom="sm" />
              </Tooltip>
              <Tooltip label="Download every decision, with the approved human call where one exists" withArrow>
                <ActionIcon variant="default" size="lg" component="a" href="/api/reviewed_decisions.jsonl" download="reviewed_decisions.jsonl" aria-label="Download decisions"><IconDownload size={18} /></ActionIcon>
              </Tooltip>
              <ActionIcon variant="default" size="lg" onClick={toggleColorScheme} aria-label="Toggle colour scheme">
                {colorScheme === "dark" ? <IconSun size={18} /> : <IconMoon size={18} />}
              </ActionIcon>
              {reviewer && (
                <Menu position="bottom-end" withArrow>
                  <Menu.Target>
                    <Button variant="subtle" color="gray" leftSection={<Avatar size="sm" color="indigo">{reviewer.name.slice(0, 2).toUpperCase()}</Avatar>}>
                      <Box visibleFrom="md"><Text size="sm" fw={600} lh={1.1}>{reviewer.name}</Text><Text size="xs" c="dimmed" lh={1.1} tt="capitalize">{reviewer.role}</Text></Box>
                    </Button>
                  </Menu.Target>
                  <Menu.Dropdown>
                    <Menu.Label>Signed in as {reviewer.name}</Menu.Label>
                    <Menu.Item leftSection={<IconUserCircle size={14} />} onClick={() => setReviewer(null)}>Switch reviewer</Menu.Item>
                    <Menu.Item leftSection={<IconLogout size={14} />} color="red" onClick={() => setReviewer(null)}>Sign out</Menu.Item>
                  </Menu.Dropdown>
                </Menu>
              )}
            </Group>
          </Group>
        </AppShell.Header>

        <AppShell.Navbar>
          <Stack gap={0} h="100%">
            <Box p="md" pb="xs">
              <SegmentedControl fullWidth size="xs" value={queue} onChange={(v) => setQueue(v as QueueKey)}
                data={QUEUES.slice(0, 3).map((q) => ({ value: q.key, label: `${q.label} · ${counts[q.key]}` }))} />
              <Select mt="xs" size="xs" value={queue} onChange={(v) => v && setQueue(v as QueueKey)} allowDeselect={false}
                data={QUEUES.map((q) => ({ value: q.key, label: `${q.label} (${counts[q.key]})` }))} aria-label="Queue" />
              <Text size="xs" c="dimmed" mt={6}>{QUEUES.find((q) => q.key === queue)!.hint}</Text>
              <TextInput mt="xs" size="xs" placeholder="Search name, hit or alert ID" leftSection={<IconSearch size={14} />}
                value={search} onChange={(e) => setSearch(e.currentTarget.value)} />
            </Box>
            <ScrollArea style={{ flex: 1 }} type="auto">
              <Queue rows={visible} selected={selected} onSelect={setSelected} />
            </ScrollArea>
          </Stack>
        </AppShell.Navbar>

        <AppShell.Main>
          {selected ? (
            <CaseView key={selected + ":" + tick} hitId={selected} onDecided={() => { refresh(); }} />
          ) : (
            summary && <Overview summary={summary} counts={counts} tick={tick} onOpenQueue={(k) => setQueue(k)} />
          )}
        </AppShell.Main>
      </AppShell>

      <Drawer opened={drawerOpen} onClose={drawer.close} position="right" size="lg"
              title={<Group gap="xs"><Text fw={700} ff="monospace">{recordId}</Text>{record && <Badge variant="light" tt="none">{record.kind.replace("_", " ")}</Badge>}</Group>}>
        {!record ? <Loader size="sm" /> : (
          <Table striped withTableBorder verticalSpacing="xs" layout="fixed">
            <Table.Tbody>
              {Object.entries(record.row).filter(([, v]) => v !== null && v !== "" && !(Array.isArray(v) && v.length === 0)).map(([k, v]) => (
                <Table.Tr key={k}>
                  <Table.Td w={150}><Text size="xs" c="dimmed">{k.replace(/_/g, " ")}</Text></Table.Td>
                  <Table.Td><Text size="sm" className="prewrap">{Array.isArray(v) ? v.join("; ") : typeof v === "object" ? <Code>{JSON.stringify(v)}</Code> : String(v)}</Text></Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        )}
      </Drawer>
    </AppCtx.Provider>
  );
}
