import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ControlPanel } from "./ControlPanel";

describe("ControlPanel", () => {
  it("calls onTriggerPump when the trigger button is clicked", async () => {
    const onTriggerPump = vi.fn();
    const user = userEvent.setup();

    render(<ControlPanel disabled={false} triggering={false} onTriggerPump={onTriggerPump} />);

    await user.click(screen.getByRole("button", { name: /trigger pump/i }));
    expect(onTriggerPump).toHaveBeenCalledOnce();
  });

  it("disables the trigger button when there is no device", () => {
    render(<ControlPanel disabled triggering={false} onTriggerPump={vi.fn()} />);

    expect(screen.getByRole("button", { name: /trigger pump/i })).toBeDisabled();
  });

  it("disables the trigger button and shows Triggering... while a pulse is in flight", () => {
    render(<ControlPanel disabled={false} triggering onTriggerPump={vi.fn()} />);

    expect(screen.getByRole("button", { name: /triggering/i })).toBeDisabled();
    expect(screen.getByText("Triggering")).toBeInTheDocument();
  });

  it("shows Idle when no pulse is in flight", () => {
    render(<ControlPanel disabled={false} triggering={false} onTriggerPump={vi.fn()} />);

    expect(screen.getByText("Idle")).toBeInTheDocument();
  });
});
