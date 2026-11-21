// A work queue as a BoardUI table: one row per case, click a row to open it.
import { Table, TableHeader, TableColumn, TableBody, TableRow, TableCell } from "@/components/base/table/table";
import { Chip } from "@/components/base/badges/chip";
import { StatusDot } from "@/components/base/badges/status-dot";
type StatusDotColor = "green" | "yellow" | "indigo";
import { Avatar } from "@/components/base/avatar/avatar";
import type { CaseRow } from "./api";
import { BUCKET, SYS, plain, useApp } from "./ui";

const DOT: Record<string, StatusDotColor> = {
  needs_decision: "yellow", returned: "yellow", pending_approval: "indigo", proposed_match: "indigo",
  proposed_clear: "green", escalated: "yellow", done: "green",
};

export default function QueueTable({ rows, onOpen }: { rows: CaseRow[]; onOpen: (id: string) => void }) {
  const { blind } = useApp();
  return (
    <div className="overflow-hidden rounded-2xl border border-separator-border bg-background-primary-default">
      <Table aria-label="Cases" selectionMode="none" onRowAction={(key) => onOpen(String(key))}>
        <TableHeader>
          <TableColumn id="name" isRowHeader className="w-[38%]">Watchlist hit</TableColumn>
          <TableColumn id="listing" className="w-[16%]">Listing</TableColumn>
          <TableColumn id="engine" className="w-[20%]">Engine says</TableColumn>
          <TableColumn id="status" className="w-[26%]">Status</TableColumn>
        </TableHeader>
        <TableBody items={rows.slice(0, 300)} renderEmptyState={() => <p className="py-12 text-center text-body-regular text-text-tertiary">Nothing in this queue.</p>}>
          {(r) => (
            <TableRow id={r.hit_id} className="cursor-pointer">
              <TableCell>
                <div className="flex items-center gap-3">
                  <Avatar size="md" color="neutral" initials={(r.hit_name || "?").replace(/[^A-Za-z]/g, "").slice(0, 1).toUpperCase()} />
                  <div className="min-w-0">
                    <p className="truncate text-body-medium text-text-primary">{r.hit_name}</p>
                    <p className="truncate text-caption-1-regular text-text-tertiary">Screened as {r.screened_name || "unknown"}</p>
                  </div>
                </div>
              </TableCell>
              <TableCell><Chip variant="subtle" color="gray">{String(r.listing || "Watchlist").split(";")[0]}</Chip></TableCell>
              <TableCell>{blind && !r.human ? <span className="text-caption-1-regular text-text-tertiary">Hidden</span> : (
                <div className="flex flex-col items-start gap-1">
                  <Chip variant="bold" color={SYS[r.system.decision].color}>{SYS[r.system.decision].label}</Chip>
                  <span className="text-caption-1-regular text-text-tertiary">{plain(r.system.reason_code)}</span>
                </div>
              )}</TableCell>
              <TableCell>
                <span className="flex items-center gap-2 text-body-2-medium text-text-secondary">
                  <StatusDot color={DOT[r.bucket]} />{BUCKET[r.bucket].label}
                  {r.human?.maker && <span className="text-caption-1-regular text-text-tertiary">· {r.human.maker}</span>}
                </span>
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
      {rows.length > 300 && <p className="border-t border-separator-border px-5 py-3 text-caption-1-regular text-text-tertiary">Showing 300 of {rows.length}. Search to narrow down.</p>}
    </div>
  );
}
