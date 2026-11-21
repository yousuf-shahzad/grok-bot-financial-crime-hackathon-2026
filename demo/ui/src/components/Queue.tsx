import { Badge, Box, Group, Stack, Text, Tooltip } from "@mantine/core";
import { IconRobot, IconFlask } from "@tabler/icons-react";
import { CaseRow, SYS_COLOR, SYS_LABEL, BUCKET_COLOR, BUCKET_LABEL, HUM_COLOR, humanize } from "../api";
import { useApp } from "../shared";

export default function Queue({ rows, selected, onSelect }: { rows: CaseRow[]; selected: string | null; onSelect: (id: string) => void }) {
  const { blind } = useApp();
  if (!rows.length) return <Text c="dimmed" size="sm" ta="center" p="xl">Nothing in this queue.</Text>;
  return (
    <Stack gap={0}>
      {rows.slice(0, 600).map((r) => (
        <Box key={r.hit_id} className="queue-item" data-active={r.hit_id === selected} px="md" py="sm"
             onClick={() => onSelect(r.hit_id)} style={{ borderBottom: "1px solid var(--mantine-color-default-border)" }}>
          <Group justify="space-between" wrap="nowrap" gap="xs">
            <Text fw={600} size="sm" truncate style={{ minWidth: 0 }}>{r.hit_name}</Text>
            <Badge size="xs" variant="light" color={BUCKET_COLOR[r.bucket]} style={{ flexShrink: 0 }}>{BUCKET_LABEL[r.bucket]}</Badge>
          </Group>
          <Text size="xs" c="dimmed" truncate>Screened as {r.screened_name || "?"} · {r.listing || "watchlist"}</Text>
          <Group gap={6} mt={6}>
            {r.human?.decision ? (
              <Badge size="xs" color={HUM_COLOR[r.human.decision]} variant="filled">{humanize(r.human.decision)} · {r.human.maker}</Badge>
            ) : blind ? (
              <Badge size="xs" variant="outline" color="gray">Engine view hidden</Badge>
            ) : (
              <Tooltip label={humanize(r.system.reason_code)} withArrow>
                <Badge size="xs" variant="dot" color={SYS_COLOR[r.system.decision]}>Engine: {SYS_LABEL[r.system.decision]}</Badge>
              </Tooltip>
            )}
            {r.qa_sample && r.bucket === "proposed_clear" && <Badge size="xs" variant="light" color="blue" leftSection={<IconFlask size={10} />}>QA</Badge>}
            {r.crossexamined && <Badge size="xs" variant="light" color="violet" leftSection={<IconRobot size={10} />}>Grok flagged</Badge>}
            <Text size="xs" c="dimmed" ff="monospace" ml="auto">{r.hit_id}</Text>
          </Group>
        </Box>
      ))}
      {rows.length > 600 && <Text size="xs" c="dimmed" ta="center" p="sm">Showing 600 of {rows.length}. Search to narrow down.</Text>}
    </Stack>
  );
}
