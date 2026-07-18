import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { toast } from "sonner";
import { describe, expect, it, vi } from "vitest";
import * as snapshotsApi from "@/lib/api/snapshots";
import type { SnapshotDTO, SnapshotPageDTO } from "@/types/api";
import { useDeleteSnapshot, useSnapshot, useSnapshots } from "./useSnapshots";

vi.mock("@/lib/api/snapshots");
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const SNAPSHOT: SnapshotDTO = {
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
};

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

describe("useSnapshots", () => {
  it("fetches the snapshot list", async () => {
    const page: SnapshotPageDTO = { items: [SNAPSHOT], total: 1, offset: 0, limit: 20 };
    vi.mocked(snapshotsApi.listSnapshots).mockResolvedValue(page);

    const { result } = renderHook(() => useSnapshots(), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(page);
  });
});

describe("useSnapshot", () => {
  it("skips fetching without an id", () => {
    const { result } = renderHook(() => useSnapshot(undefined), { wrapper });
    expect(result.current.fetchStatus).toBe("idle");
    expect(snapshotsApi.getSnapshot).not.toHaveBeenCalled();
  });

  it("fetches the detail once an id is given", async () => {
    vi.mocked(snapshotsApi.getSnapshot).mockResolvedValue(SNAPSHOT);
    const { result } = renderHook(() => useSnapshot("snap-1"), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(snapshotsApi.getSnapshot).toHaveBeenCalledWith("snap-1");
  });
});

describe("useDeleteSnapshot", () => {
  it("deletes a snapshot and shows a success toast", async () => {
    vi.mocked(snapshotsApi.deleteSnapshot).mockResolvedValue(undefined);
    const { result } = renderHook(() => useDeleteSnapshot(), { wrapper });

    result.current.mutate("snap-1");

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(snapshotsApi.deleteSnapshot).toHaveBeenCalledWith("snap-1");
    expect(toast.success).toHaveBeenCalledWith("Snapshot deleted");
  });

  it("shows an error toast when deletion fails", async () => {
    vi.mocked(snapshotsApi.deleteSnapshot).mockRejectedValue(new Error("cannot delete"));
    const { result } = renderHook(() => useDeleteSnapshot(), { wrapper });

    result.current.mutate("snap-1");

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(toast.error).toHaveBeenCalledWith("cannot delete");
  });
});
