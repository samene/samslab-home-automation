import { Loader2, TriangleAlert } from "lucide-react";
import { useTerminal } from "@/hooks/useTerminal";
import { TerminalToolbar } from "./TerminalToolbar";

interface TerminalPanelProps {
  deviceId: string;
  deviceName: string | undefined;
  /** Mirrors CameraPanel's own `active`-gated effect pattern: only wire up the
   * WebSocket/xterm.js instance while the drawer is actually open. */
  active: boolean;
}

/** The drawer's body: xterm.js host + toolbar + connection-state overlays. */
export function TerminalPanel({ deviceId, deviceName, active }: TerminalPanelProps) {
  const {
    containerRef,
    status,
    shell,
    errorMessage,
    closedReason,
    copySelection,
    pasteFromClipboard,
    clear,
    requestCloseSession,
  } = useTerminal(deviceId, active);

  return (
    <div className="flex h-full min-h-0 flex-col gap-2" data-testid="terminal-panel">
      <TerminalToolbar
        deviceName={deviceName}
        status={status}
        shell={shell}
        onCopy={copySelection}
        onPaste={pasteFromClipboard}
        onClear={clear}
        onTerminate={requestCloseSession}
      />

      <div className="relative min-h-0 flex-1 overflow-hidden rounded-xl bg-[#0b0f14] p-2">
        <div ref={containerRef} className="size-full" data-testid="terminal-xterm-host" />

        {status === "connecting" ? (
          <div
            className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-[#0b0f14]/90 text-white"
            data-testid="terminal-connecting"
          >
            <Loader2 className="size-6 animate-spin" />
            <p className="text-sm font-medium">Connecting to device…</p>
          </div>
        ) : null}

        {status === "reconnecting" ? (
          <div className="absolute top-2 right-2 flex items-center gap-1.5 rounded-full bg-warning/90 px-2.5 py-1 text-xs font-medium text-warning-foreground">
            <Loader2 className="size-3 animate-spin" />
            Reconnecting…
          </div>
        ) : null}

        {errorMessage ? (
          <div
            className="absolute inset-x-2 bottom-2 flex items-center gap-2 rounded-lg bg-destructive/90 px-3 py-2 text-xs font-medium text-destructive-foreground"
            data-testid="terminal-error"
          >
            <TriangleAlert className="size-3.5 shrink-0" />
            {errorMessage}
          </div>
        ) : null}

        {closedReason ? (
          <div
            className="absolute inset-x-2 bottom-2 flex items-center gap-2 rounded-lg bg-muted px-3 py-2 text-xs font-medium text-muted-foreground"
            data-testid="terminal-session-ended"
          >
            Session ended ({closedReason}). Reopen the terminal to start a new one.
          </div>
        ) : null}
      </div>
    </div>
  );
}
