import { Clipboard, ClipboardPaste, Eraser, Power, TerminalSquare } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { TerminalConnectionStatus } from "@/lib/terminal/TerminalService";
import { cn } from "@/lib/utils";

interface TerminalToolbarProps {
  deviceName: string | undefined;
  status: TerminalConnectionStatus;
  shell: string | null;
  onCopy: () => void;
  onPaste: () => void;
  onClear: () => void;
  onTerminate: () => void;
}

const STATUS_LABEL: Record<TerminalConnectionStatus, string> = {
  connecting: "Connecting…",
  open: "Connected",
  reconnecting: "Reconnecting…",
  closed: "Disconnected",
  error: "Connection error",
};

const STATUS_BADGE_VARIANT: Record<TerminalConnectionStatus, "success" | "warning" | "destructive"> =
  {
    connecting: "warning",
    reconnecting: "warning",
    open: "success",
    closed: "destructive",
    error: "destructive",
  };

/** The drawer's header row: identity, live connection status, and per-session actions. */
export function TerminalToolbar({
  deviceName,
  status,
  shell,
  onCopy,
  onPaste,
  onClear,
  onTerminate,
}: TerminalToolbarProps) {
  return (
    <div
      className="flex shrink-0 items-center justify-between gap-2 border-b border-border/60 pb-2"
      data-testid="terminal-toolbar"
    >
      <div className="flex min-w-0 items-center gap-2">
        <TerminalSquare className="size-4 shrink-0 text-muted-foreground" />
        <span className="truncate text-sm font-semibold">
          {deviceName ? `${deviceName} — Terminal` : "Terminal"}
        </span>
        <Badge variant={STATUS_BADGE_VARIANT[status]} className="shrink-0 rounded-full">
          {STATUS_LABEL[status]}
        </Badge>
        {shell ? (
          <span className="hidden shrink-0 truncate text-xs text-muted-foreground sm:inline">
            {shell}
          </span>
        ) : null}
      </div>

      <div className="flex shrink-0 items-center gap-1">
        <Button
          type="button"
          variant="ghost"
          size="icon"
          title="Copy selection"
          aria-label="Copy selection"
          onClick={onCopy}
        >
          <Clipboard className="size-4" />
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          title="Paste from clipboard"
          aria-label="Paste from clipboard"
          onClick={onPaste}
        >
          <ClipboardPaste className="size-4" />
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          title="Clear screen"
          aria-label="Clear screen"
          onClick={onClear}
        >
          <Eraser className="size-4" />
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          title="Terminate session"
          aria-label="Terminate session"
          className={cn("text-destructive hover:bg-destructive/10 hover:text-destructive")}
          onClick={onTerminate}
        >
          <Power className="size-4" />
        </Button>
      </div>
    </div>
  );
}
