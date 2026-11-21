import { createContext, useContext } from "react";
import { Badge, Tooltip } from "@mantine/core";

export interface Reviewer { name: string; role: "analyst" | "checker" | "qa" }

export const AppCtx = createContext<{
  openRecord: (id: string) => void;
  reviewer: Reviewer | null;
  blind: boolean;
  refresh: () => void;
}>({ openRecord: () => {}, reviewer: null, blind: false, refresh: () => {} });

export const useApp = () => useContext(AppCtx);

const KIND_COLOR: Record<string, string> = { CUS: "blue", KYC: "grape", NOTE: "cyan", SR: "orange", H: "red", A: "gray", ACC: "gray", APP: "gray" };

/** A record ID that opens the underlying record in the side drawer. */
export function IdChip({ id }: { id?: string | null }) {
  const { openRecord } = useApp();
  if (!id) return null;
  const prefix = id.split("-")[0];
  return (
    <Tooltip label="Open record" withArrow openDelay={300}>
      <Badge className="id-chip" variant="light" color={KIND_COLOR[prefix] || "gray"} tt="none" size="sm"
             onClick={(e) => { e.stopPropagation(); openRecord(id); }}>
        {id}
      </Badge>
    </Tooltip>
  );
}
