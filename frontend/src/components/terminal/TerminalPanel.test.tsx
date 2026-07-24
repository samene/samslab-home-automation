import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useTerminal } from "@/hooks/useTerminal";
import { TerminalPanel } from "./TerminalPanel";

vi.mock("@/hooks/useTerminal");

const mockedUseTerminal = vi.mocked(useTerminal);

function baseResult(overrides: Partial<ReturnType<typeof useTerminal>> = {}) {
  return {
    containerRef: { current: null },
    status: "connecting",
    shell: null,
    errorMessage: null,
    closedReason: null,
    copySelection: vi.fn(),
    pasteFromClipboard: vi.fn(),
    clear: vi.fn(),
    requestCloseSession: vi.fn(),
    ...overrides,
  } as ReturnType<typeof useTerminal>;
}

describe("TerminalPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows a connecting overlay while status is connecting", () => {
    mockedUseTerminal.mockReturnValue(baseResult({ status: "connecting" }));
    render(<TerminalPanel deviceId="device-1" deviceName="Backyard Pi" active />);

    expect(screen.getByTestId("terminal-connecting")).toBeInTheDocument();
    expect(screen.getByText(/backyard pi — terminal/i)).toBeInTheDocument();
  });

  it("hides the connecting overlay once open and shows the shell", () => {
    mockedUseTerminal.mockReturnValue(baseResult({ status: "open", shell: "/bin/bash" }));
    render(<TerminalPanel deviceId="device-1" deviceName="Backyard Pi" active />);

    expect(screen.queryByTestId("terminal-connecting")).not.toBeInTheDocument();
    expect(screen.getByText("/bin/bash")).toBeInTheDocument();
    expect(screen.getByText("Connected")).toBeInTheDocument();
  });

  it("shows a reconnecting indicator without covering the terminal", () => {
    mockedUseTerminal.mockReturnValue(baseResult({ status: "reconnecting" }));
    render(<TerminalPanel deviceId="device-1" deviceName="Backyard Pi" active />);

    // Both the toolbar status badge and the overlay indicator say "Reconnecting…".
    expect(screen.getAllByText(/reconnecting/i).length).toBeGreaterThan(0);
    expect(screen.queryByTestId("terminal-connecting")).not.toBeInTheDocument();
  });

  it("surfaces an error message banner", () => {
    mockedUseTerminal.mockReturnValue(
      baseResult({ status: "open", errorMessage: "Failed to start a shell on this device" }),
    );
    render(<TerminalPanel deviceId="device-1" deviceName="Backyard Pi" active />);

    expect(screen.getByTestId("terminal-error")).toHaveTextContent(
      "Failed to start a shell on this device",
    );
  });

  it("surfaces a session-ended banner", () => {
    mockedUseTerminal.mockReturnValue(
      baseResult({ status: "closed", closedReason: "shell_exited" }),
    );
    render(<TerminalPanel deviceId="device-1" deviceName="Backyard Pi" active />);

    expect(screen.getByTestId("terminal-session-ended")).toHaveTextContent("shell_exited");
  });

  it("wires the toolbar's copy/paste/clear/terminate actions to the hook", async () => {
    const user = userEvent.setup();
    const result = baseResult({ status: "open", shell: "/bin/bash" });
    mockedUseTerminal.mockReturnValue(result);
    render(<TerminalPanel deviceId="device-1" deviceName="Backyard Pi" active />);

    await user.click(screen.getByRole("button", { name: /copy selection/i }));
    await user.click(screen.getByRole("button", { name: /paste from clipboard/i }));
    await user.click(screen.getByRole("button", { name: /clear screen/i }));
    await user.click(screen.getByRole("button", { name: /terminate session/i }));

    expect(result.copySelection).toHaveBeenCalledOnce();
    expect(result.pasteFromClipboard).toHaveBeenCalledOnce();
    expect(result.clear).toHaveBeenCalledOnce();
    expect(result.requestCloseSession).toHaveBeenCalledOnce();
  });

  it("passes deviceId and active through to useTerminal", () => {
    mockedUseTerminal.mockReturnValue(baseResult());
    render(<TerminalPanel deviceId="device-42" deviceName="Greenhouse" active={false} />);

    expect(mockedUseTerminal).toHaveBeenCalledWith("device-42", false);
  });
});
