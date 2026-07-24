import { useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { TerminalPanel } from "./TerminalPanel";

interface TerminalDrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  deviceId: string | undefined;
  deviceName: string | undefined;
}

const MIN_HEIGHT_PX = 240;
const DEFAULT_HEIGHT_PX = 420;

/**
 * A resizable bottom drawer hosting one device's interactive terminal.
 *
 * Built on the same `Sheet`/`SheetContent side="bottom"` primitive the
 * mobile nav uses (Radix Dialog under the hood) rather than a bespoke
 * overlay — same focus-trap/Escape-to-close/scroll-lock behavior for free.
 * Radix unmounts `SheetContent`'s children when closed, which is
 * deliberate here, not a limitation: closing the drawer tears down this
 * browser's WebSocket/xterm.js instance (see `useTerminal`), but the PTY
 * session itself lives on the server/agent and survives — reopening
 * reattaches to it rather than starting a new shell (see
 * docs/agent/TERMINAL.md). Only the visible scrollback resets; `cd`,
 * environment variables, and running programs do not.
 */
export function TerminalDrawer({ open, onOpenChange, deviceId, deviceName }: TerminalDrawerProps) {
  const [height, setHeight] = useState(DEFAULT_HEIGHT_PX);
  const draggingRef = useRef(false);

  function handlePointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    draggingRef.current = true;
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function handlePointerMove(event: ReactPointerEvent<HTMLDivElement>) {
    if (!draggingRef.current) return;
    const proposedHeight = window.innerHeight - event.clientY;
    const maxHeight = window.innerHeight * 0.9;
    setHeight(Math.min(maxHeight, Math.max(MIN_HEIGHT_PX, proposedHeight)));
  }

  function handlePointerUp(event: ReactPointerEvent<HTMLDivElement>) {
    draggingRef.current = false;
    event.currentTarget.releasePointerCapture(event.pointerId);
  }

  if (!deviceId) return null;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="bottom"
        className="flex max-h-[90vh] flex-col gap-0 p-0"
        style={{ height }}
        data-testid="terminal-drawer"
      >
        <SheetTitle className="sr-only">Device Terminal</SheetTitle>
        <div
          className="flex h-3 w-full shrink-0 cursor-row-resize touch-none items-center justify-center"
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          data-testid="terminal-drawer-resize-handle"
        >
          <div className="h-1 w-10 rounded-full bg-border" />
        </div>
        <div className="min-h-0 flex-1 px-3 pb-3">
          <TerminalPanel deviceId={deviceId} deviceName={deviceName} active={open} />
        </div>
      </SheetContent>
    </Sheet>
  );
}
