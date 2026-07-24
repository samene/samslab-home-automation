import { API_BASE_URL } from "@/lib/api/client";
import { getAccessToken } from "@/lib/api/tokenStore";
import {
  buildEnvelope,
  type TerminalClosedPayload,
  type TerminalEnvelope,
  type TerminalErrorPayload,
  type TerminalOpenedPayload,
  type TerminalOutputPayload,
} from "./protocol";

/**
 * The browser-facing terminal WebSocket (`server/app/terminal/router.py`) —
 * this project's one deliberate exception to "live updates come from
 * polling, not a browser WebSocket" (see frontend/README.md): an
 * interactive shell fundamentally needs a real duplex, low-latency byte
 * stream, which polling cannot provide.
 *
 * Path is fixed at `/ws/terminal/{deviceId}`, matching the server's
 * `TERMINAL_WEBSOCKET_PATH` default — the same "REST paths are hardcoded
 * client-side, not read from server config" convention every other file
 * under `lib/api/` already follows.
 */
const TERMINAL_WS_PATH = "/ws/terminal";

const _RECONNECT_DELAYS_MS = [500, 1000, 2000, 4000, 8000, 15000];
const HANDSHAKE_TIMEOUT_MS = 10000;

/**
 * Maps a server-initiated close code (`app/websocket/constants.py`'s
 * `CloseCode`, reused by `app/terminal/router.py`) to a message worth
 * showing the user. Everything else (1000 normal, 1001 going away, and —
 * critically — 1006 abnormal closure, which is what the browser reports
 * for a WebSocket upgrade that never got a real response at all, e.g. the
 * backend not yet having this route deployed) still schedules a reconnect,
 * but with a generic "couldn't reach" message so a stuck "Connecting…"
 * screen never happens silently — see the incident this comment exists for.
 */
const CLOSE_CODE_MESSAGES: Record<number, string> = {
  4400: "The terminal connection was rejected (protocol error).",
  4401: "You are not authorized to open a terminal on this device.",
  4404: "This device is not currently connected.",
  4408: "The terminal handshake timed out.",
};

export type TerminalConnectionStatus =
  | "connecting"
  | "open"
  | "reconnecting"
  | "closed"
  | "error";

export interface TerminalServiceCallbacks {
  onStatusChange: (status: TerminalConnectionStatus, detail?: string) => void;
  onOpened: (shell: string) => void;
  onOutput: (data: string) => void;
  /** The PTY session itself ended (shell exited, idle timeout, explicit close) — not reconnectable. */
  onSessionClosed: (reason: string) => void;
  onError: (code: string, message: string) => void;
}

function wsUrlFor(deviceId: string): string {
  const wsBase = API_BASE_URL.replace(/^http/, "ws");
  return `${wsBase}${TERMINAL_WS_PATH}/${deviceId}`;
}

/**
 * One browser-side terminal connection for one device.
 *
 * Session identity is server-assigned, never client-minted: this class
 * sends a proposed `session_id` with its first `TERMINAL_OPEN` purely as a
 * wire-format formality (the payload schema requires one), but the
 * authoritative ID — and whether it's a brand-new session or a reattach to
 * one already running — comes back in `TERMINAL_OPENED`/relayed events. A
 * reconnect (network blip, drawer reopened) opens a fresh WebSocket and
 * relies entirely on the server reusing the still-alive PTY session; this
 * class holds no PTY state of its own to carry across reconnects.
 */
export class TerminalService {
  private readonly deviceId: string;
  private readonly callbacks: TerminalServiceCallbacks;
  private ws: WebSocket | null = null;
  private intentionallyClosed = false;
  private reconnectAttempt = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | undefined;
  private handshakeTimer: ReturnType<typeof setTimeout> | undefined;
  private cols: number;
  private rows: number;

  constructor(
    deviceId: string,
    callbacks: TerminalServiceCallbacks,
    initialSize: { cols: number; rows: number },
  ) {
    this.deviceId = deviceId;
    this.callbacks = callbacks;
    this.cols = initialSize.cols;
    this.rows = initialSize.rows;
  }

  connect(): void {
    this.intentionallyClosed = false;
    this.openSocket();
  }

  /** Send raw input bytes; a no-op while not connected (buffering keystrokes across a
   * reconnect would risk replaying them out of order once the session resumes). */
  sendInput(data: string): void {
    this.send("TERMINAL_INPUT", { session_id: crypto.randomUUID(), data });
  }

  resize(cols: number, rows: number): void {
    this.cols = cols;
    this.rows = rows;
    this.send("TERMINAL_RESIZE", { session_id: crypto.randomUUID(), cols, rows });
  }

  /** Explicitly terminate the PTY session itself (not just this connection). */
  requestClose(reason = "user_requested"): void {
    this.send("TERMINAL_CLOSE", { session_id: crypto.randomUUID(), reason });
  }

  /** Close this connection without ending the underlying session — it stays alive
   * server-side (see docs/agent/TERMINAL.md) for a later reconnect to resume. */
  disconnect(): void {
    this.intentionallyClosed = true;
    clearTimeout(this.reconnectTimer);
    clearTimeout(this.handshakeTimer);
    this.ws?.close(1000, "client_disconnect");
    this.ws = null;
  }

  private send(messageType: "TERMINAL_INPUT" | "TERMINAL_RESIZE" | "TERMINAL_CLOSE" | "TERMINAL_OPEN", payload: Record<string, unknown>): void {
    if (this.ws?.readyState !== WebSocket.OPEN) return;
    this.ws.send(JSON.stringify(buildEnvelope(messageType, payload)));
  }

  private openSocket(): void {
    this.callbacks.onStatusChange(this.reconnectAttempt === 0 ? "connecting" : "reconnecting");
    const socket = new WebSocket(wsUrlFor(this.deviceId));
    this.ws = socket;

    socket.addEventListener("open", () => {
      const token = getAccessToken();
      socket.send(
        JSON.stringify(
          buildEnvelope("HELLO", {
            token: token ?? "",
            agent_version: "frontend",
            capabilities: [],
          }),
        ),
      );
      this.handshakeTimer = setTimeout(() => {
        socket.close(4408, "handshake_timeout");
      }, HANDSHAKE_TIMEOUT_MS);
    });

    socket.addEventListener("message", (event: MessageEvent<string>) => {
      this.handleMessage(event.data);
    });

    socket.addEventListener("close", (event: CloseEvent) => {
      clearTimeout(this.handshakeTimer);
      if (this.intentionallyClosed) {
        this.callbacks.onStatusChange("closed");
        return;
      }
      // Every unexpected close gets a visible reason — previously this was
      // silent, which meant any handshake-time rejection (bad auth, device
      // not connected, or the backend not having this route deployed yet)
      // looked identical to "still connecting" forever, with no way for a
      // user to tell something was actually wrong.
      const message =
        CLOSE_CODE_MESSAGES[event.code] ??
        "Couldn't reach the device terminal service. Retrying…";
      this.callbacks.onError("connection_closed", message);
      this.scheduleReconnect();
    });

    // The browser deliberately exposes no detail on a WebSocket "error"
    // event (see the MDN docs) — the "close" handler above, which does get
    // a real code/reason, is the only place worth reporting anything from.
    socket.addEventListener("error", () => {});
  }

  private handleMessage(raw: string): void {
    let envelope: TerminalEnvelope;
    try {
      envelope = JSON.parse(raw) as TerminalEnvelope;
    } catch {
      return;
    }
    switch (envelope.message_type) {
      case "WELCOME": {
        clearTimeout(this.handshakeTimer);
        this.reconnectAttempt = 0;
        this.send("TERMINAL_OPEN", {
          session_id: crypto.randomUUID(),
          cols: this.cols,
          rows: this.rows,
        });
        break;
      }
      case "TERMINAL_OPENED": {
        const payload = envelope.payload as unknown as TerminalOpenedPayload;
        this.callbacks.onStatusChange("open");
        this.callbacks.onOpened(payload.shell);
        break;
      }
      case "TERMINAL_OUTPUT": {
        const payload = envelope.payload as unknown as TerminalOutputPayload;
        this.callbacks.onOutput(payload.data);
        break;
      }
      case "TERMINAL_CLOSED": {
        const payload = envelope.payload as unknown as TerminalClosedPayload;
        this.intentionallyClosed = true; // a closed session is never auto-reconnected
        this.callbacks.onSessionClosed(payload.reason);
        this.ws?.close(1000, "session_closed");
        break;
      }
      case "TERMINAL_ERROR": {
        const payload = envelope.payload as unknown as TerminalErrorPayload;
        this.callbacks.onError(payload.code, payload.message);
        break;
      }
      default:
        break;
    }
  }

  private scheduleReconnect(): void {
    if (this.intentionallyClosed) return;
    const delay =
      _RECONNECT_DELAYS_MS[Math.min(this.reconnectAttempt, _RECONNECT_DELAYS_MS.length - 1)];
    this.reconnectAttempt += 1;
    this.callbacks.onStatusChange("reconnecting");
    this.reconnectTimer = setTimeout(() => this.openSocket(), delay);
  }
}
