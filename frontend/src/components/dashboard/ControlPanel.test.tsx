import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ControlPanel } from "./ControlPanel";

describe("ControlPanel", () => {
  it("calls the watering callbacks when their buttons are clicked", async () => {
    const onStartWatering = vi.fn();
    const onStopWatering = vi.fn();
    const user = userEvent.setup();

    render(
      <ControlPanel
        disabled={false}
        pumpState="Idle"
        onStartWatering={onStartWatering}
        onStopWatering={onStopWatering}
      />,
    );

    await user.click(screen.getByRole("button", { name: /start pump/i }));
    expect(onStartWatering).toHaveBeenCalledOnce();

    await user.click(screen.getByRole("button", { name: /stop pump/i }));
    expect(onStopWatering).toHaveBeenCalledOnce();
  });

  it("disables the watering buttons when there is no device", () => {
    render(
      <ControlPanel disabled pumpState="Unknown" onStartWatering={vi.fn()} onStopWatering={vi.fn()} />,
    );

    expect(screen.getByRole("button", { name: /start pump/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /stop pump/i })).toBeDisabled();
  });

  it("shows the current pump status", () => {
    render(
      <ControlPanel disabled={false} pumpState="Active" onStartWatering={vi.fn()} onStopWatering={vi.fn()} />,
    );

    expect(screen.getByText("Running")).toBeInTheDocument();
  });
});
