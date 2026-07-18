import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useDevices } from "@/hooks/useDevices";
import { useDeleteSnapshot, useSnapshot, useSnapshots } from "@/hooks/useSnapshots";
import type { DevicePageDTO, SnapshotDTO } from "@/types/api";
import { SnapshotsPage } from "./SnapshotsPage";

vi.mock("@/hooks/useDevices");
vi.mock("@/hooks/useSnapshots");

const mockedUseDevices = vi.mocked(useDevices);
const mockedUseSnapshots = vi.mocked(useSnapshots);
const mockedUseSnapshot = vi.mocked(useSnapshot);
const mockedUseDeleteSnapshot = vi.mocked(useDeleteSnapshot);

const DEVICES: DevicePageDTO = {
  items: [
    {
      id: "device-1",
      device_name: "backyard-pi",
      hostname: "backyard-pi.local",
      display_name: "Backyard Pi",
      description: null,
      status: "ONLINE",
      last_seen: null,
      agent_version: null,
      protocol_version: null,
      registered_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
      enabled: true,
      metadata: {},
      capabilities: [],
    },
  ],
  total: 1,
  offset: 0,
  limit: 100,
};

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
    workflow_id: null,
    workflow_name: null,
    ...overrides,
  };
}

function makeSnapshots(total: number): SnapshotDTO[] {
  return Array.from({ length: total }, (_, index) => makeSnapshot({ id: `snap-${index}` }));
}

describe("SnapshotsPage", () => {
  beforeEach(() => {
    mockedUseDevices.mockReturnValue({ data: DEVICES } as unknown as ReturnType<typeof useDevices>);
    mockedUseDeleteSnapshot.mockReturnValue({
      mutateAsync: vi.fn().mockResolvedValue(undefined),
      isPending: false,
    } as unknown as ReturnType<typeof useDeleteSnapshot>);
    mockedUseSnapshot.mockReturnValue({ data: undefined, isLoading: false } as unknown as ReturnType<
      typeof useSnapshot
    >);
  });

  it("shows a loading skeleton while fetching", () => {
    mockedUseSnapshots.mockReturnValue({ data: undefined, isLoading: true } as unknown as ReturnType<
      typeof useSnapshots
    >);

    render(<SnapshotsPage />);

    expect(screen.getByText("Snapshots")).toBeInTheDocument();
  });

  it("shows an empty state when there are no snapshots", () => {
    mockedUseSnapshots.mockReturnValue({
      data: { items: [], total: 0, offset: 0, limit: 20 },
      isLoading: false,
    } as unknown as ReturnType<typeof useSnapshots>);

    render(<SnapshotsPage />);

    expect(screen.getByText("No snapshots yet.")).toBeInTheDocument();
  });

  it("renders a grid of snapshot cards and disables pagination when everything fits on one page", () => {
    mockedUseSnapshots.mockReturnValue({
      data: { items: makeSnapshots(3), total: 3, offset: 0, limit: 20 },
      isLoading: false,
    } as unknown as ReturnType<typeof useSnapshots>);

    render(<SnapshotsPage />);

    expect(screen.getAllByText("Backyard Pi")).toHaveLength(3);
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
  });

  it("enables Next when there are more pages, and opens the lightbox on card click", async () => {
    mockedUseSnapshots.mockReturnValue({
      data: { items: makeSnapshots(20), total: 45, offset: 0, limit: 20 },
      isLoading: false,
    } as unknown as ReturnType<typeof useSnapshots>);
    mockedUseSnapshot.mockReturnValue({ data: makeSnapshot(), isLoading: false } as unknown as ReturnType<
      typeof useSnapshot
    >);

    const user = userEvent.setup();
    render(<SnapshotsPage />);

    expect(screen.getByRole("button", { name: "Next" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();

    await user.click(screen.getAllByRole("img")[0]);
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });
});
