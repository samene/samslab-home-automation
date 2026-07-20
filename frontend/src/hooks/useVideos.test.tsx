import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { toast } from "sonner";
import { describe, expect, it, vi } from "vitest";
import * as videosApi from "@/lib/api/videos";
import type { SavedMediaDTO, SavedMediaPageDTO } from "@/types/api";
import { useDeleteVideo, useVideo, useVideos } from "./useVideos";

vi.mock("@/lib/api/videos");
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const VIDEO: SavedMediaDTO = {
  id: "vid-1",
  media_type: "VIDEO",
  device_id: "device-1",
  command_id: "cmd-1",
  filename: "clip.mp4",
  thumbnail_url: "",
  image_url: "",
  video_url: "https://s3.example.com/clip.mp4",
  etag: "etag-1",
  sha256: "abc123",
  width: 1920,
  height: 1080,
  duration: 65,
  fps: 30,
  bitrate: 8000,
  size: 10_485_760,
  captured_at: "2026-01-15T10:00:00Z",
  created_at: "2026-01-15T10:00:01Z",
  metadata: {},
  workflow_id: null,
  workflow_name: null,
};

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

describe("useVideos", () => {
  it("fetches the video list", async () => {
    const page: SavedMediaPageDTO = { items: [VIDEO], total: 1, offset: 0, limit: 20 };
    vi.mocked(videosApi.listVideos).mockResolvedValue(page);

    const { result } = renderHook(() => useVideos(), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(page);
  });
});

describe("useVideo", () => {
  it("skips fetching without an id", () => {
    const { result } = renderHook(() => useVideo(undefined), { wrapper });
    expect(result.current.fetchStatus).toBe("idle");
    expect(videosApi.getVideo).not.toHaveBeenCalled();
  });

  it("fetches the detail once an id is given", async () => {
    vi.mocked(videosApi.getVideo).mockResolvedValue(VIDEO);
    const { result } = renderHook(() => useVideo("vid-1"), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(videosApi.getVideo).toHaveBeenCalledWith("vid-1");
  });
});

describe("useDeleteVideo", () => {
  it("deletes a video and shows a success toast", async () => {
    vi.mocked(videosApi.deleteVideo).mockResolvedValue(undefined);
    const { result } = renderHook(() => useDeleteVideo(), { wrapper });

    result.current.mutate("vid-1");

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(videosApi.deleteVideo).toHaveBeenCalledWith("vid-1");
    expect(toast.success).toHaveBeenCalledWith("Video deleted");
  });

  it("shows an error toast when deletion fails", async () => {
    vi.mocked(videosApi.deleteVideo).mockRejectedValue(new Error("cannot delete"));
    const { result } = renderHook(() => useDeleteVideo(), { wrapper });

    result.current.mutate("vid-1");

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(toast.error).toHaveBeenCalledWith("cannot delete");
  });
});
