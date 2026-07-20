import { ListChecks, Search, Trash2, X } from "lucide-react";
import { useMemo, useState } from "react";
import { HistoryTimeline } from "@/components/history/HistoryTimeline";
import { ConfirmDialog } from "@/components/shared/ConfirmDialog";
import { CardGridSkeleton } from "@/components/shared/LoadingSkeleton";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useBulkDeleteCommands, useCommands } from "@/hooks/useCommands";
import { useDevices } from "@/hooks/useDevices";
import type { CommandStatus } from "@/types/api";

const PAGE_SIZE = 50;
const STATUS_OPTIONS: CommandStatus[] = [
  "PENDING",
  "QUEUED",
  "DISPATCHED",
  "RUNNING",
  "COMPLETED",
  "FAILED",
  "CANCELLED",
  "EXPIRED",
  "TIMEOUT",
];

export function HistoryPage() {
  const [offset, setOffset] = useState(0);
  const [statusFilter, setStatusFilter] = useState<CommandStatus | "">("");
  const [deviceFilter, setDeviceFilter] = useState<string>("");
  const [search, setSearch] = useState("");
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [showBulkDeleteConfirm, setShowBulkDeleteConfirm] = useState(false);

  const { data: devicesPage } = useDevices({ limit: 100 });
  const { data: commandsPage, isLoading } = useCommands({
    offset,
    limit: PAGE_SIZE,
    status: statusFilter || undefined,
    device: deviceFilter || undefined,
  });
  const bulkDeleteCommands = useBulkDeleteCommands();

  const deviceNameById = useMemo(() => {
    const map: Record<string, string> = {};
    for (const device of devicesPage?.items ?? []) {
      map[device.id] = device.display_name;
    }
    return map;
  }, [devicesPage]);

  const commands = useMemo(() => {
    const items = commandsPage?.items ?? [];
    const query = search.trim().toLowerCase();
    if (!query) return items;
    return items.filter(
      (command) =>
        command.command_type.toLowerCase().includes(query) ||
        (deviceNameById[command.device_id] ?? "").toLowerCase().includes(query),
    );
  }, [commandsPage, search, deviceNameById]);

  const total = commandsPage?.total ?? 0;
  const hasNextPage = offset + PAGE_SIZE < total;
  const hasPreviousPage = offset > 0;
  const allVisibleSelected = commands.length > 0 && commands.every((command) => selectedIds.has(command.id));

  function resetToFirstPage() {
    setOffset(0);
  }

  function toggleSelectionMode() {
    setSelectionMode((current) => !current);
    setSelectedIds(new Set());
  }

  function toggleSelect(commandId: string) {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(commandId)) {
        next.delete(commandId);
      } else {
        next.add(commandId);
      }
      return next;
    });
  }

  function toggleSelectAll() {
    setSelectedIds((current) => {
      if (allVisibleSelected) return new Set();
      const next = new Set(current);
      for (const command of commands) next.add(command.id);
      return next;
    });
  }

  async function handleConfirmBulkDelete() {
    await bulkDeleteCommands.mutateAsync(Array.from(selectedIds));
    setShowBulkDeleteConfirm(false);
    setSelectedIds(new Set());
    setSelectionMode(false);
  }

  return (
    <div className="h-full overflow-y-auto p-4 sm:p-6 lg:p-8">
      <div className="flex flex-col gap-5">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">History</h1>
          <p className="text-sm text-muted-foreground">Every command ever sent, newest first.</p>
        </div>

        <div className="flex flex-col gap-3 md:flex-row md:items-center md:flex-wrap">
          <div className="relative flex-1 md:min-w-[12rem]">
            <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder="Search by command or device…"
              className="h-10 rounded-xl pl-9"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </div>

          <select
            value={statusFilter}
            onChange={(event) => {
              setStatusFilter(event.target.value as CommandStatus | "");
              resetToFirstPage();
            }}
            className="h-10 rounded-xl border border-input bg-transparent px-3 text-sm shadow-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring coarse:h-11"
          >
            <option value="">All statuses</option>
            {STATUS_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>

          <select
            value={deviceFilter}
            onChange={(event) => {
              setDeviceFilter(event.target.value);
              resetToFirstPage();
            }}
            className="h-10 rounded-xl border border-input bg-transparent px-3 text-sm shadow-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring coarse:h-11"
          >
            <option value="">All devices</option>
            {(devicesPage?.items ?? []).map((device) => (
              <option key={device.id} value={device.id}>
                {device.display_name}
              </option>
            ))}
          </select>

          <Button
            type="button"
            variant={selectionMode ? "secondary" : "outline"}
            size="sm"
            className="h-10 rounded-xl"
            onClick={toggleSelectionMode}
          >
            {selectionMode ? <X className="size-4" /> : <ListChecks className="size-4" />}
            {selectionMode ? "Cancel" : "Select"}
          </Button>
        </div>

        {selectionMode ? (
          <div className="flex items-center justify-between gap-3 rounded-xl border border-border bg-muted/50 px-4 py-3">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                className="size-4 rounded border-input accent-primary coarse:size-5"
                checked={allVisibleSelected}
                onChange={toggleSelectAll}
              />
              Select all
              <span className="text-muted-foreground">
                ({selectedIds.size} selected)
              </span>
            </label>
            <Button
              type="button"
              variant="destructive"
              size="sm"
              className="rounded-lg"
              disabled={selectedIds.size === 0}
              onClick={() => setShowBulkDeleteConfirm(true)}
            >
              <Trash2 className="size-3.5" />
              Delete{selectedIds.size > 0 ? ` (${selectedIds.size})` : ""}
            </Button>
          </div>
        ) : null}

        {isLoading ? (
          <CardGridSkeleton count={5} />
        ) : (
          <HistoryTimeline
            commands={commands}
            deviceNameById={deviceNameById}
            selectionMode={selectionMode}
            selectedIds={selectedIds}
            onToggleSelect={toggleSelect}
          />
        )}

        <div className="flex items-center justify-between text-sm text-muted-foreground">
          <span>
            {total === 0
              ? "No activity"
              : `${offset + 1}–${Math.min(offset + PAGE_SIZE, total)} of ${total}`}
          </span>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              className="rounded-lg"
              disabled={!hasPreviousPage}
              onClick={() => setOffset((current) => Math.max(0, current - PAGE_SIZE))}
            >
              Previous
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="rounded-lg"
              disabled={!hasNextPage}
              onClick={() => setOffset((current) => current + PAGE_SIZE)}
            >
              Next
            </Button>
          </div>
        </div>
      </div>

      <ConfirmDialog
        open={showBulkDeleteConfirm}
        onOpenChange={setShowBulkDeleteConfirm}
        title={`Delete ${selectedIds.size} command${selectedIds.size === 1 ? "" : "s"}?`}
        description="Permanently remove the selected commands from history. Only finished commands can be deleted — any others in the selection will be skipped."
        confirmLabel="Delete"
        variant="destructive"
        isConfirming={bulkDeleteCommands.isPending}
        onConfirm={() => void handleConfirmBulkDelete()}
      />
    </div>
  );
}
