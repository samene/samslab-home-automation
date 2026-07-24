import { FitAddon } from "@xterm/addon-fit";
import { SearchAddon } from "@xterm/addon-search";
import { WebLinksAddon } from "@xterm/addon-web-links";
import { Terminal } from "@xterm/xterm";
import "@xterm/xterm/css/xterm.css";
import { useEffect, useRef, useState } from "react";
import {
  TerminalService,
  type TerminalConnectionStatus,
} from "@/lib/terminal/TerminalService";

/**
 * Wires one xterm.js instance to one `TerminalService` WebSocket connection
 * for the lifetime of `active`. Deliberately not split into a separate
 * "xterm setup" vs. "WebSocket setup" effect: the two must be created and
 * torn down together (input/output/resize wiring references both), and
 * splitting them risks a stale closure over one while the other reconnects.
 *
 * See docs/agent/TERMINAL.md: mounting this hook always opens a fresh
 * WebSocket, but the server reuses the still-alive PTY session underneath
 * if one exists (e.g. the drawer was previously opened for this device and
 * never explicitly closed) — shell state (cwd, env, history, running
 * programs) survives a remount even though the xterm.js scrollback buffer
 * itself does not.
 */
export interface UseTerminalResult {
  containerRef: React.RefObject<HTMLDivElement | null>;
  status: TerminalConnectionStatus;
  shell: string | null;
  errorMessage: string | null;
  closedReason: string | null;
  copySelection: () => void;
  pasteFromClipboard: () => void;
  clear: () => void;
  requestCloseSession: () => void;
}

const DEFAULT_FONT_FAMILY =
  'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace';

export function useTerminal(deviceId: string | undefined, active: boolean): UseTerminalResult {
  const containerRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<Terminal | null>(null);
  const serviceRef = useRef<TerminalService | null>(null);
  const [status, setStatus] = useState<TerminalConnectionStatus>("connecting");
  const [shell, setShell] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [closedReason, setClosedReason] = useState<string | null>(null);

  useEffect(() => {
    if (!active || !deviceId) return;
    const container = containerRef.current;
    if (!container) return;

    setShell(null);
    setErrorMessage(null);
    setClosedReason(null);

    const term = new Terminal({
      cursorBlink: true,
      fontSize: 13,
      fontFamily: DEFAULT_FONT_FAMILY,
      scrollback: 5000,
      allowProposedApi: true,
      theme: {
        background: "#0b0f14",
        foreground: "#e2e8f0",
        cursor: "#38bdf8",
      },
    });
    const fitAddon = new FitAddon();
    const searchAddon = new SearchAddon();
    term.loadAddon(fitAddon);
    term.loadAddon(new WebLinksAddon());
    term.loadAddon(searchAddon);
    term.open(container);
    fitAddon.fit();
    term.focus();
    termRef.current = term;

    const service = new TerminalService(
      deviceId,
      {
        onStatusChange: setStatus,
        onOpened: (openedShell) => {
          setShell(openedShell);
          setErrorMessage(null);
        },
        onOutput: (data) => term.write(data),
        onSessionClosed: (reason) => {
          setClosedReason(reason);
          term.write(`\r\n\x1b[90m[session ended: ${reason}]\x1b[0m\r\n`);
        },
        onError: (_code, message) => setErrorMessage(message),
      },
      { cols: term.cols, rows: term.rows },
    );
    serviceRef.current = service;
    service.connect();

    const dataDisposable = term.onData((data) => service.sendInput(data));
    // Fires whenever xterm.js's own cols/rows change (including the initial
    // fit() above) — the one place PTY resize is triggered from; no
    // separate "send initial size" step needed.
    const resizeDisposable = term.onResize(({ cols, rows }) => service.resize(cols, rows));

    const resizeObserver = new ResizeObserver(() => fitAddon.fit());
    resizeObserver.observe(container);

    return () => {
      resizeObserver.disconnect();
      dataDisposable.dispose();
      resizeDisposable.dispose();
      service.disconnect();
      term.dispose();
      termRef.current = null;
      serviceRef.current = null;
    };
  }, [active, deviceId]);

  function copySelection() {
    const term = termRef.current;
    if (!term) return;
    const selection = term.getSelection();
    if (selection) void navigator.clipboard.writeText(selection);
  }

  function pasteFromClipboard() {
    const service = serviceRef.current;
    if (!service) return;
    void navigator.clipboard.readText().then((text) => {
      if (text) service.sendInput(text);
    });
  }

  function clear() {
    termRef.current?.clear();
  }

  function requestCloseSession() {
    serviceRef.current?.requestClose();
  }

  return {
    containerRef,
    status,
    shell,
    errorMessage,
    closedReason,
    copySelection,
    pasteFromClipboard,
    clear,
    requestCloseSession,
  };
}
