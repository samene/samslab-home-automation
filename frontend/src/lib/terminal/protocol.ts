/**
 * The wire shapes for the browser-facing terminal WebSocket
 * (`server/app/terminal/router.py`), mirroring `shared/protocol/schemas.py`'s
 * `Envelope`/`Terminal*Payload` Pydantic models on the Python side — this is
 * the same envelope format the agent<->server WebSocket Gateway uses, just
 * carried over a second connection this browser opens directly (see
 * `docs/architecture/PROTOCOL.md`).
 */

export type TerminalMessageType =
  | "HELLO"
  | "WELCOME"
  | "TERMINAL_OPEN"
  | "TERMINAL_OPENED"
  | "TERMINAL_INPUT"
  | "TERMINAL_OUTPUT"
  | "TERMINAL_RESIZE"
  | "TERMINAL_CLOSE"
  | "TERMINAL_CLOSED"
  | "TERMINAL_ERROR";

export interface TerminalEnvelope<TPayload = Record<string, unknown>> {
  message_id: string;
  timestamp: string;
  protocol_version: number;
  message_type: TerminalMessageType;
  payload: TPayload;
  correlation_id: string | null;
  trace_id: string | null;
}

export interface HelloPayload {
  token: string;
  agent_version: string;
  capabilities: string[];
}

export interface TerminalOpenPayload {
  session_id: string;
  cols: number;
  rows: number;
}

export interface TerminalOpenedPayload {
  session_id: string;
  shell: string;
}

export interface TerminalInputPayload {
  session_id: string;
  data: string;
}

export interface TerminalOutputPayload {
  session_id: string;
  data: string;
}

export interface TerminalResizePayload {
  session_id: string;
  cols: number;
  rows: number;
}

export interface TerminalClosePayload {
  session_id: string;
  reason: string | null;
}

export interface TerminalClosedPayload {
  session_id: string;
  reason: string;
  exit_code: number | null;
}

export interface TerminalErrorPayload {
  session_id: string | null;
  code: string;
  message: string;
}

const PROTOCOL_VERSION = 1;

/** Builds one outgoing envelope with client-generated `message_id`/`timestamp`. */
export function buildEnvelope<TPayload extends Record<string, unknown>>(
  messageType: TerminalMessageType,
  payload: TPayload,
): TerminalEnvelope<TPayload> {
  return {
    message_id: crypto.randomUUID(),
    timestamp: new Date().toISOString(),
    protocol_version: PROTOCOL_VERSION,
    message_type: messageType,
    payload,
    correlation_id: null,
    trace_id: null,
  };
}
