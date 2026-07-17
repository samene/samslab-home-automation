import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ConfirmDialog } from "./ConfirmDialog";

describe("ConfirmDialog", () => {
  it("renders the title and description when open", () => {
    render(
      <ConfirmDialog
        open
        onOpenChange={() => {}}
        title="Stop Pump"
        description="Send pump.stop to the device?"
        onConfirm={() => {}}
      />,
    );
    expect(screen.getByText("Stop Pump")).toBeInTheDocument();
    expect(screen.getByText("Send pump.stop to the device?")).toBeInTheDocument();
  });

  it("renders nothing when closed", () => {
    render(
      <ConfirmDialog
        open={false}
        onOpenChange={() => {}}
        title="Stop Pump"
        description="Send pump.stop to the device?"
        onConfirm={() => {}}
      />,
    );
    expect(screen.queryByText("Stop Pump")).not.toBeInTheDocument();
  });

  it("calls onConfirm when the confirm button is clicked", async () => {
    const onConfirm = vi.fn();
    const user = userEvent.setup();
    render(
      <ConfirmDialog
        open
        onOpenChange={() => {}}
        title="Stop Pump"
        description="Send pump.stop to the device?"
        confirmLabel="Send"
        onConfirm={onConfirm}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Send" }));
    expect(onConfirm).toHaveBeenCalledOnce();
  });

  it("calls onOpenChange(false) when cancel is clicked", async () => {
    const onOpenChange = vi.fn();
    const user = userEvent.setup();
    render(
      <ConfirmDialog
        open
        onOpenChange={onOpenChange}
        title="Stop Pump"
        description="Send pump.stop to the device?"
        onConfirm={() => {}}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("disables buttons and shows a working label while confirming", () => {
    render(
      <ConfirmDialog
        open
        onOpenChange={() => {}}
        title="Stop Pump"
        description="Send pump.stop to the device?"
        isConfirming
        onConfirm={() => {}}
      />,
    );
    expect(screen.getByRole("button", { name: /working/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
  });
});
