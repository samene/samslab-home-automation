import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TerminalDrawer } from "./TerminalDrawer";

vi.mock("./TerminalPanel", () => ({
  TerminalPanel: ({ deviceId, deviceName, active }: Record<string, unknown>) => (
    <div data-testid="mock-terminal-panel">
      {String(deviceId)}:{String(deviceName)}:{String(active)}
    </div>
  ),
}));

describe("TerminalDrawer", () => {
  it("renders nothing when there is no device", () => {
    const { container } = render(
      <TerminalDrawer open={true} onOpenChange={vi.fn()} deviceId={undefined} deviceName={undefined} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("does not mount the terminal panel while closed", () => {
    render(
      <TerminalDrawer
        open={false}
        onOpenChange={vi.fn()}
        deviceId="device-1"
        deviceName="Backyard Pi"
      />,
    );
    expect(screen.queryByTestId("mock-terminal-panel")).not.toBeInTheDocument();
  });

  it("mounts the terminal panel with active=true while open", () => {
    render(
      <TerminalDrawer
        open={true}
        onOpenChange={vi.fn()}
        deviceId="device-1"
        deviceName="Backyard Pi"
      />,
    );
    const panel = screen.getByTestId("mock-terminal-panel");
    expect(panel).toHaveTextContent("device-1:Backyard Pi:true");
  });

  it("shows the resize handle while open", () => {
    render(
      <TerminalDrawer
        open={true}
        onOpenChange={vi.fn()}
        deviceId="device-1"
        deviceName="Backyard Pi"
      />,
    );
    expect(screen.getByTestId("terminal-drawer-resize-handle")).toBeInTheDocument();
  });
});
