// Tryll sidebar: BoardUI's dashboard-sidebar styling (floating panel, gradient selected row,
// sidebar theme switcher) wired to our work queues instead of the demo links.
import type { ComponentType } from "react";
import { RiLogoutBoxRLine } from "@remixicon/react";
import { ThemeToggle } from "@/components/application/theme/theme-toggle";
import { Counter } from "@/components/base/badges/counter";
import { Switch } from "@/components/base/switch/switch";
import { Avatar } from "@/components/base/avatar/avatar";
import { cx } from "@/utils/cx";
import type { Reviewer } from "./ui";

export interface NavEntry { key: string; label: string; icon: ComponentType<{ className?: string }>; count?: number }

function Row({ entry, selected, onSelect }: { entry: NavEntry; selected: boolean; onSelect: () => void }) {
  const Icon = entry.icon;
  return (
    <button type="button" onClick={onSelect} aria-current={selected ? "page" : undefined}
      className={cx("relative flex w-full items-center justify-between rounded-2lg px-3 py-2.5 text-left transition-colors duration-200",
        selected ? "bg-linear-to-b from-accent-500 to-accent-600 shadow-nav-selected" : "hover:bg-background-secondary-hover")}>
      {selected && <span className="absolute top-2 bottom-2 left-0 w-1 rounded-full bg-gold-500" />}
      <span className="flex min-w-0 items-center gap-2">
        <Icon className={cx("size-5 shrink-0", selected ? "text-white" : "text-foreground-icon-secondary")} />
        <span className={cx("text-body-medium whitespace-nowrap", selected ? "text-white" : "text-text-secondary")}>{entry.label}</span>
      </span>
      {entry.count !== undefined && entry.count > 0 && (
        selected ? <span className="text-caption-1-semibold text-white/90">{entry.count}</span> : <Counter>{entry.count}</Counter>
      )}
    </button>
  );
}

export default function Sidebar({ main, queues, selected, onSelect, reviewer, onSignOut, blind, setBlind }: {
  main: NavEntry; queues: NavEntry[]; selected: string; onSelect: (k: string) => void;
  reviewer: Reviewer | null; onSignOut: () => void; blind: boolean; setBlind: (b: boolean) => void;
}) {
  return (
    <aside className="m-4 flex w-[264px] shrink-0 flex-col justify-between rounded-2xl bg-background-primary-default p-4 shadow-[0_1px_2px_rgba(0,0,0,0.04),0_0_0_1px_var(--color-separator-border)]">
      <div className="flex flex-col gap-7">
        <div className="px-2 pt-2 pb-1">
          <img src="/tryll-logo.webp" alt="Tryll" className="h-14 w-auto dark:rounded-lg dark:bg-white dark:p-1.5" />
        </div>
        <nav className="flex flex-col gap-1"><Row entry={main} selected={selected === main.key} onSelect={() => onSelect(main.key)} /></nav>
        <div className="flex flex-col gap-1.5">
          <p className="px-2 pb-1.5 text-caption-1-medium text-text-tertiary">Work queues</p>
          {queues.map((q) => <Row key={q.key} entry={q} selected={selected === q.key} onSelect={() => onSelect(q.key)} />)}
        </div>
      </div>
      <div className="flex flex-col gap-3">
        <div className="rounded-2lg bg-background-secondary-default px-3 py-2.5">
          <Switch isSelected={blind} onChange={setBlind} size="sm"><span className="text-body-2-medium text-text-secondary">Blind review</span></Switch>
        </div>
        <ThemeToggle appearance="sidebar-segmented" />
        {reviewer && (
          <div className="flex items-center gap-2 rounded-2lg px-2 py-1.5">
            <Avatar size="sm" color="blue" initials={reviewer.name.slice(0, 1).toUpperCase()} />
            <span className="min-w-0 flex-1"><span className="block truncate text-body-2-semibold text-text-primary">{reviewer.name}</span><span className="block text-caption-1-regular text-text-tertiary capitalize">{reviewer.role}</span></span>
            <button type="button" onClick={onSignOut} aria-label="Switch reviewer" className="rounded-md p-1 text-foreground-icon-secondary hover:bg-background-secondary-hover"><RiLogoutBoxRLine className="size-4" /></button>
          </div>
        )}
      </div>
    </aside>
  );
}
