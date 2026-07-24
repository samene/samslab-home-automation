import { render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useTerminal } from "./useTerminal";

const { termInstances, MockTerminal } = vi.hoisted(() => {
  class MockTerminalImpl {
    cols = 80;
    rows = 24;
    options: unknown;
    write = vi.fn();
    focus = vi.fn();
    dispose = vi.fn();
    clear = vi.fn();
    loadAddon = vi.fn();
    open = vi.fn();
    getSelection = vi.fn(() => "selected-text");
    private dataHandlers: Array<(data: string) => void> = [];
    private resizeHandlers: Array<(size: { cols: number; rows: number }) => void> = [];

    constructor(options: unknown) {
      this.options = options;
      termInstances.push(this);
    }

    onData(handler: (data: string) => void) {
      this.dataHandlers.push(handler);
      return { dispose: vi.fn() };
    }

    onResize(handler: (size: { cols: number; rows: number }) => void) {
      this.resizeHandlers.push(handler);
      return { dispose: vi.fn() };
    }

    emitData(data: string) {
      this.dataHandlers.forEach((h) => h(data));
    }

    emitResize(size: { cols: number; rows: number }) {
      this.resizeHandlers.forEach((h) => h(size));
    }
  }
  const termInstances: MockTerminalImpl[] = [];
  return { termInstances, MockTerminal: MockTerminalImpl };
});

vi.mock("@xterm/xterm", () => ({ Terminal: MockTerminal }));
vi.mock("@xterm/addon-fit", () => ({
  FitAddon: class {
    fit = vi.fn();
  },
}));
vi.mock("@xterm/addon-web-links", () => ({
  WebLinksAddon: class {},
}));
vi.mock("@xterm/addon-search", () => ({
  SearchAddon: class {},
}));

const { serviceInstances, MockTerminalService } = vi.hoisted(() => {
  class MockTerminalServiceImpl {
    static lastArgs: unknown[] = [];
    connect = vi.fn();
    sendInput = vi.fn();
    resize = vi.fn();
    disconnect = vi.fn();
    requestClose = vi.fn();
    callbacks: Record<string, (...args: unknown[]) => void>;

    constructor(deviceId: string, callbacks: Record<string, (...args: unknown[]) => void>, size: unknown) {
      MockTerminalServiceImpl.lastArgs = [deviceId, callbacks, size];
      this.callbacks = callbacks;
      serviceInstances.push(this);
    }
  }
  const serviceInstances: MockTerminalServiceImpl[] = [];
  return { serviceInstances, MockTerminalService: MockTerminalServiceImpl };
});

vi.mock("@/lib/terminal/TerminalService", () => ({ TerminalService: MockTerminalService }));

class MockResizeObserver {
  observe = vi.fn();
  disconnect = vi.fn();
  unobserve = vi.fn();
}

function Host({ deviceId, active }: { deviceId: string | undefined; active: boolean }) {
  const { containerRef } = useTerminal(deviceId, active);
  return <div ref={containerRef} data-testid="host" />;
}

describe("useTerminal", () => {
  beforeEach(() => {
    termInstances.length = 0;
    serviceInstances.length = 0;
    vi.stubGlobal("ResizeObserver", MockResizeObserver);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("creates a Terminal, opens it in the container, and connects a TerminalService", () => {
    render(<Host deviceId="device-1" active={true} />);

    expect(termInstances).toHaveLength(1);
    expect(termInstances[0].open).toHaveBeenCalledOnce();
    expect(termInstances[0].focus).toHaveBeenCalledOnce();
    expect(serviceInstances).toHaveLength(1);
    expect(serviceInstances[0].connect).toHaveBeenCalledOnce();
  });

  it("does nothing while inactive", () => {
    render(<Host deviceId="device-1" active={false} />);

    expect(termInstances).toHaveLength(0);
    expect(serviceInstances).toHaveLength(0);
  });

  it("does nothing without a deviceId", () => {
    render(<Host deviceId={undefined} active={true} />);

    expect(termInstances).toHaveLength(0);
  });

  it("forwards typed data to the service as TERMINAL_INPUT", () => {
    render(<Host deviceId="device-1" active={true} />);

    termInstances[0].emitData("ls\n");

    expect(serviceInstances[0].sendInput).toHaveBeenCalledWith("ls\n");
  });

  it("forwards xterm resize events to the service", () => {
    render(<Host deviceId="device-1" active={true} />);

    termInstances[0].emitResize({ cols: 120, rows: 40 });

    expect(serviceInstances[0].resize).toHaveBeenCalledWith(120, 40);
  });

  it("writes TERMINAL_OUTPUT data to the terminal via the onOutput callback", () => {
    render(<Host deviceId="device-1" active={true} />);

    serviceInstances[0].callbacks.onOutput("hello\n");

    expect(termInstances[0].write).toHaveBeenCalledWith("hello\n");
  });

  it("disposes the terminal and disconnects the service on unmount", () => {
    const { unmount } = render(<Host deviceId="device-1" active={true} />);

    unmount();

    expect(termInstances[0].dispose).toHaveBeenCalledOnce();
    expect(serviceInstances[0].disconnect).toHaveBeenCalledOnce();
  });

  it("recreates the terminal and service when deviceId changes", () => {
    const { rerender } = render(<Host deviceId="device-1" active={true} />);
    expect(termInstances).toHaveLength(1);

    rerender(<Host deviceId="device-2" active={true} />);

    expect(termInstances).toHaveLength(2);
    expect(serviceInstances[0].disconnect).toHaveBeenCalledOnce();
    expect(serviceInstances).toHaveLength(2);
  });
});
