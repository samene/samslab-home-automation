import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { TerminalLauncherCard } from "./TerminalLauncherCard";

describe("TerminalLauncherCard", () => {
  it("calls onOpen when clicked", async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    render(<TerminalLauncherCard disabled={false} onOpen={onOpen} />);

    await user.click(screen.getByTestId("open-terminal-button"));

    expect(onOpen).toHaveBeenCalledOnce();
  });

  it("is disabled when disabled is true", () => {
    render(<TerminalLauncherCard disabled={true} onOpen={vi.fn()} />);
    expect(screen.getByTestId("open-terminal-button")).toBeDisabled();
  });
});
