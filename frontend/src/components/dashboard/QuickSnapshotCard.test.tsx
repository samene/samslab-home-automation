import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { useTakeSnapshot } from "@/hooks/useCamera";
import { QuickSnapshotCard } from "./QuickSnapshotCard";

vi.mock("@/hooks/useCamera");

const mockedUseTakeSnapshot = vi.mocked(useTakeSnapshot);

describe("QuickSnapshotCard", () => {
  it("calls takeSnapshot when the button is clicked", async () => {
    const mutate = vi.fn();
    mockedUseTakeSnapshot.mockReturnValue({ mutate, isPending: false } as unknown as ReturnType<
      typeof useTakeSnapshot
    >);
    const user = userEvent.setup();

    render(<QuickSnapshotCard hasDevice />);

    await user.click(screen.getByRole("button", { name: /take snapshot/i }));
    expect(mutate).toHaveBeenCalledOnce();
  });

  it("disables the button when there is no device", () => {
    mockedUseTakeSnapshot.mockReturnValue({ mutate: vi.fn(), isPending: false } as unknown as ReturnType<
      typeof useTakeSnapshot
    >);

    render(<QuickSnapshotCard hasDevice={false} />);

    expect(screen.getByRole("button", { name: /take snapshot/i })).toBeDisabled();
  });

  it("disables the button and shows Capturing… while pending", () => {
    mockedUseTakeSnapshot.mockReturnValue({ mutate: vi.fn(), isPending: true } as unknown as ReturnType<
      typeof useTakeSnapshot
    >);

    render(<QuickSnapshotCard hasDevice />);

    expect(screen.getByRole("button", { name: /capturing/i })).toBeDisabled();
  });
});
