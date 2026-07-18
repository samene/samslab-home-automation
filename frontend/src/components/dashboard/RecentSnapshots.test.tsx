import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useDeleteSnapshot, useSnapshot, useSnapshots } from "@/hooks/useSnapshots";
import type { SnapshotDTO } from "@/types/api";
import { RecentSnapshots } from "./RecentSnapshots";

vi.mock("@/hooks/useSnapshots");

const mockedUseSnapshots = vi.mocked(useSnapshots);
const mockedUseSnapshot = vi.mocked(useSnapshot);
const mockedUseDeleteSnapshot = vi.mocked(useDeleteSnapshot);

function makeSnapshot(overrides: Partial<SnapshotDTO> = {}): SnapshotDTO {
  return {
    id: "snap-1",
    device_id: "device-1",
    command_id: "cmd-1",
    filename: "snap-1.jpg",
    thumbnail_url: "https://s3.example.com/thumb.jpg",
    image_url: "https://s3.example.com/full.jpg",
    etag: "etag-1",
    sha256: "abc123",
    width: 1920,
    height: 1080,
    size: 204800,
    captured_at: "2026-01-15T10:00:00Z",
    created_at: "2026-01-15T10:00:01Z",
    metadata: {},
    ...overrides,
  };
}

describe("RecentSnapshots", () => {
  beforeEach(() => {
    mockedUseDeleteSnapshot.mockReturnValue({
      mutateAsync: vi.fn().mockResolvedValue(undefined),
      isPending: false,
    } as unknown as ReturnType<typeof useDeleteSnapshot>);
    mockedUseSnapshot.mockReturnValue({ data: undefined, isLoading: false } as unknown as ReturnType<
      typeof useSnapshot
    >);
  });

  it("shows an empty state when there are no snapshots", () => {
    mockedUseSnapshots.mockReturnValue({
      data: { items: [], total: 0, offset: 0, limit: 3 },
    } as unknown as ReturnType<typeof useSnapshots>);

    render(<RecentSnapshots />);

    expect(screen.getByText("No snapshots yet.")).toBeInTheDocument();
  });

  it("shows up to 3 thumbnails and opens the lightbox on click", async () => {
    const snapshots = [
      makeSnapshot({ id: "snap-1" }),
      makeSnapshot({ id: "snap-2" }),
      makeSnapshot({ id: "snap-3" }),
    ];
    mockedUseSnapshots.mockReturnValue({
      data: { items: snapshots, total: 3, offset: 0, limit: 3 },
    } as unknown as ReturnType<typeof useSnapshots>);
    mockedUseSnapshot.mockReturnValue({ data: snapshots[0], isLoading: false } as unknown as ReturnType<
      typeof useSnapshot
    >);

    const user = userEvent.setup();
    render(<RecentSnapshots />);

    const thumbnails = screen.getAllByRole("img");
    expect(thumbnails).toHaveLength(3);

    await user.click(thumbnails[0]);
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });
});
