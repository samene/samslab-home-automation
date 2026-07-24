import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as tokenStore from "@/lib/api/tokenStore";
import { TerminalService, type TerminalServiceCallbacks } from "./TerminalService";

vi.mock("@/lib/api/tokenStore");

const { instances, MockWebSocket } = vi.hoisted(() => {
  class MockSocket {
    static OPEN = 1;
    static CONNECTING = 0;
    static CLOSED = 3;
    readyState = 0;
    url: string;
    sent: string[] = [];
    closeCalls: Array<{ code?: number; reason?: string }> = [];
    private listeners: Record<string, Array<(event: unknown) => void>> = {};

    constructor(url: string) {
      this.url = url;
      instances.push(this);
    }

    addEventListener(event: string, handler: (event: unknown) => void) {
      (this.listeners[event] ??= []).push(handler);
    }

    removeEventListener(event: string, handler: (event: unknown) => void) {
      this.listeners[event] = (this.listeners[event] ?? []).filter((h) => h !== handler);
    }

    send(data: string) {
      this.sent.push(data);
    }

    close(code?: number, reason?: string) {
      this.readyState = MockSocket.CLOSED;
      this.closeCalls.push({ code, reason });
      this.listeners.close?.forEach((h) => h({ code: code ?? 1000, reason: reason ?? "" }));
    }

    simulateOpen() {
      this.readyState = MockSocket.OPEN;
      this.listeners.open?.forEach((h) => h({}));
    }

    simulateMessage(data: unknown) {
      this.listeners.message?.forEach((h) => h({ data: JSON.stringify(data) }));
    }

    simulateServerClose(code = 1006, reason = "") {
      this.readyState = MockSocket.CLOSED;
      this.listeners.close?.forEach((h) => h({ code, reason }));
    }
  }
  const instances: MockSocket[] = [];
  return { instances, MockWebSocket: MockSocket };
});

function envelope(messageType: string, payload: Record<string, unknown>) {
  return {
    message_id: "m-1",
    timestamp: new Date().toISOString(),
    protocol_version: 1,
    message_type: messageType,
    payload,
    correlation_id: null,
    trace_id: null,
  };
}

function callbacks(): TerminalServiceCallbacks {
  return {
    onStatusChange: vi.fn(),
    onOpened: vi.fn(),
    onOutput: vi.fn(),
    onSessionClosed: vi.fn(),
    onError: vi.fn(),
  };
}

describe("TerminalService", () => {
  beforeEach(() => {
    instances.length = 0;
    vi.stubGlobal("WebSocket", MockWebSocket);
    vi.mocked(tokenStore.getAccessToken).mockReturnValue("the-access-token");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("connects and sends HELLO with the current access token once the socket opens", () => {
    const service = new TerminalService("device-1", callbacks(), { cols: 80, rows: 24 });
    service.connect();
    instances[0].simulateOpen();

    const hello = JSON.parse(instances[0].sent[0]);
    expect(hello.message_type).toBe("HELLO");
    expect(hello.payload.token).toBe("the-access-token");
  });

  it("sends TERMINAL_OPEN with the current size once WELCOME is received", () => {
    const service = new TerminalService("device-1", callbacks(), { cols: 100, rows: 40 });
    service.connect();
    instances[0].simulateOpen();
    instances[0].simulateMessage(envelope("WELCOME", { session_id: "s", server_time: "now" }));

    const open = JSON.parse(instances[0].sent[1]);
    expect(open.message_type).toBe("TERMINAL_OPEN");
    expect(open.payload.cols).toBe(100);
    expect(open.payload.rows).toBe(40);
  });

  it("reports status open and the shell once TERMINAL_OPENED arrives", () => {
    const cb = callbacks();
    const service = new TerminalService("device-1", cb, { cols: 80, rows: 24 });
    service.connect();
    instances[0].simulateOpen();
    instances[0].simulateMessage(envelope("TERMINAL_OPENED", { session_id: "s", shell: "/bin/bash" }));

    expect(cb.onStatusChange).toHaveBeenCalledWith("open");
    expect(cb.onOpened).toHaveBeenCalledWith("/bin/bash");
  });

  it("forwards TERMINAL_OUTPUT bytes to onOutput", () => {
    const cb = callbacks();
    const service = new TerminalService("device-1", cb, { cols: 80, rows: 24 });
    service.connect();
    instances[0].simulateOpen();
    instances[0].simulateMessage(envelope("TERMINAL_OUTPUT", { session_id: "s", data: "hello\n" }));

    expect(cb.onOutput).toHaveBeenCalledWith("hello\n");
  });

  it("reports errors without ending the connection", () => {
    const cb = callbacks();
    const service = new TerminalService("device-1", cb, { cols: 80, rows: 24 });
    service.connect();
    instances[0].simulateOpen();
    instances[0].simulateMessage(
      envelope("TERMINAL_ERROR", { session_id: null, code: "spawn_failed", message: "boom" }),
    );

    expect(cb.onError).toHaveBeenCalledWith("spawn_failed", "boom");
    expect(cb.onSessionClosed).not.toHaveBeenCalled();
  });

  it("reports TERMINAL_CLOSED as a session end and does not reconnect", () => {
    const cb = callbacks();
    const service = new TerminalService("device-1", cb, { cols: 80, rows: 24 });
    service.connect();
    instances[0].simulateOpen();
    instances[0].simulateMessage(
      envelope("TERMINAL_CLOSED", { session_id: "s", reason: "shell_exited", exit_code: 0 }),
    );

    expect(cb.onSessionClosed).toHaveBeenCalledWith("shell_exited");
    // The mock's close() triggers its own "close" listener synchronously,
    // which is where reconnect-scheduling would happen if it were going to.
    instances[0].simulateServerClose();
    expect(instances).toHaveLength(1);
  });

  it("sends TERMINAL_INPUT only while the socket is open", () => {
    const service = new TerminalService("device-1", callbacks(), { cols: 80, rows: 24 });
    service.connect();
    service.sendInput("echo hi\n");
    expect(instances[0].sent).toHaveLength(0);

    instances[0].simulateOpen();
    service.sendInput("echo hi\n");
    const input = JSON.parse(instances[0].sent.at(-1)!);
    expect(input.message_type).toBe("TERMINAL_INPUT");
    expect(input.payload.data).toBe("echo hi\n");
  });

  it("sends TERMINAL_RESIZE with the new dimensions", () => {
    const service = new TerminalService("device-1", callbacks(), { cols: 80, rows: 24 });
    service.connect();
    instances[0].simulateOpen();
    service.resize(120, 50);

    const resize = JSON.parse(instances[0].sent.at(-1)!);
    expect(resize.message_type).toBe("TERMINAL_RESIZE");
    expect(resize.payload).toMatchObject({ cols: 120, rows: 50 });
  });

  it("sends TERMINAL_CLOSE when requestClose is called", () => {
    const service = new TerminalService("device-1", callbacks(), { cols: 80, rows: 24 });
    service.connect();
    instances[0].simulateOpen();
    service.requestClose("user_requested");

    const close = JSON.parse(instances[0].sent.at(-1)!);
    expect(close.message_type).toBe("TERMINAL_CLOSE");
    expect(close.payload.reason).toBe("user_requested");
  });

  it("disconnect() closes the socket without sending TERMINAL_CLOSE and does not reconnect", () => {
    const cb = callbacks();
    const service = new TerminalService("device-1", cb, { cols: 80, rows: 24 });
    service.connect();
    instances[0].simulateOpen();
    const sentBefore = instances[0].sent.length;

    service.disconnect();

    expect(instances[0].sent).toHaveLength(sentBefore);
    expect(instances).toHaveLength(1); // no reconnect attempt scheduled
  });

  it("schedules a reconnect after an unexpected close", async () => {
    vi.useFakeTimers();
    const service = new TerminalService("device-1", callbacks(), { cols: 80, rows: 24 });
    service.connect();
    instances[0].simulateOpen();

    instances[0].simulateServerClose();
    await vi.advanceTimersByTimeAsync(1000);

    expect(instances.length).toBeGreaterThan(1);
    vi.useRealTimers();
  });

  // Regression coverage: an unexpected close previously scheduled a silent
  // reconnect with no user-visible signal at all, which is indistinguishable
  // from "still connecting" — see the incident this fixes.
  it("reports a specific message for a recognized close code", () => {
    const cb = callbacks();
    const service = new TerminalService("device-1", cb, { cols: 80, rows: 24 });
    service.connect();
    instances[0].simulateOpen();

    instances[0].simulateServerClose(4404, "device_unavailable");

    expect(cb.onError).toHaveBeenCalledWith(
      "connection_closed",
      "This device is not currently connected.",
    );
  });

  it("reports a generic message for an unrecognized close code (e.g. the route not existing yet)", () => {
    const cb = callbacks();
    const service = new TerminalService("device-1", cb, { cols: 80, rows: 24 });
    service.connect();
    instances[0].simulateOpen();

    instances[0].simulateServerClose(1006, "");

    expect(cb.onError).toHaveBeenCalledWith(
      "connection_closed",
      expect.stringContaining("Couldn't reach"),
    );
  });

  it("never silently closes without reporting an error, even before the socket ever opens", () => {
    const cb = callbacks();
    const service = new TerminalService("device-1", cb, { cols: 80, rows: 24 });
    service.connect();

    // The socket failed before ever reaching "open" — e.g. the server has
    // no route at this path yet. Browsers report this as an abrupt close,
    // typically code 1006, with no prior "open" event.
    instances[0].simulateServerClose(1006, "");

    expect(cb.onError).toHaveBeenCalledOnce();
    expect(cb.onStatusChange).toHaveBeenCalledWith("reconnecting");
  });

  it("does not report an error for an intentional disconnect", () => {
    const cb = callbacks();
    const service = new TerminalService("device-1", cb, { cols: 80, rows: 24 });
    service.connect();
    instances[0].simulateOpen();

    service.disconnect();

    expect(cb.onError).not.toHaveBeenCalled();
  });
});
