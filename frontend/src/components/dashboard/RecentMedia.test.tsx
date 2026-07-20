import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useDeleteSnapshot, useSnapshot, useSnapshots } from "@/hooks/useSnapshots";
import { useDeleteVideo, useVideo, useVideos } from "@/hooks/useVideos";
import type { SavedMediaDTO } from "@/types/api";
import { RecentMedia } from "./RecentMedia";

vi.mock("@/hooks/useSnapshots");
vi.mock("@/hooks/useVideos");

const mockedUseSnapshots = vi.mocked(useSnapshots);
const mockedUseSnapshot = vi.mocked(useSnapshot);
const mockedUseDeleteSnapshot = vi.mocked(useDeleteSnapshot);
const mockedUseVideos = vi.mocked(useVideos);
const mockedUseVideo = vi.mocked(useVideo);
const mockedUseDeleteVideo = vi.mocked(useDeleteVideo);

function makeMedia(overrides: Partial<SavedMediaDTO> = {}): SavedMediaDTO {
  return {
    id: "snap-1",
    media_type: "IMAGE",
    device_id: "device-1",
    command_id: "cmd-1",
    filename: "snap-1.jpg",
    thumbnail_url: "https://s3.example.com/thumb.jpg",
    image_url: "https://s3.example.com/full.jpg",
    video_url: "",
    etag: "etag-1",
    sha256: "abc123",
    width: 1920,
    height: 1080,
    duration: null,
    fps: null,
    bitrate: null,
    size: 204800,
    captured_at: "2026-01-15T10:00:00Z",
    created_at: "2026-01-15T10:00:01Z",
    metadata: {},
    workflow_id: null,
    workflow_name: null,
    ...overrides,
  };
}

describe("RecentMedia", () => {
  beforeEach(() => {
    mockedUseDeleteSnapshot.mockReturnValue({
      mutateAsync: vi.fn().mockResolvedValue(undefined),
      isPending: false,
    } as unknown as ReturnType<typeof useDeleteSnapshot>);
    mockedUseDeleteVideo.mockReturnValue({
      mutateAsync: vi.fn().mockResolvedValue(undefined),
      isPending: false,
    } as unknown as ReturnType<typeof useDeleteVideo>);
    mockedUseSnapshot.mockReturnValue({ data: undefined, isLoading: false } as unknown as ReturnType<
      typeof useSnapshot
    >);
    mockedUseVideo.mockReturnValue({ data: undefined, isLoading: false } as unknown as ReturnType<
      typeof useVideo
    >);
  });

  it("shows an empty state when there is no media", () => {
    mockedUseSnapshots.mockReturnValue({
      data: { items: [], total: 0, offset: 0, limit: 3 },
    } as unknown as ReturnType<typeof useSnapshots>);
    mockedUseVideos.mockReturnValue({
      data: { items: [], total: 0, offset: 0, limit: 3 },
    } as unknown as ReturnType<typeof useVideos>);

    render(<RecentMedia />);

    expect(screen.getByText("No media yet.")).toBeInTheDocument();
  });

  it("merges images and videos, newest first, capped at 3", () => {
    const image = makeMedia({
      id: "img-1",
      media_type: "IMAGE",
      captured_at: "2026-01-15T09:00:00Z",
    });
    const video = makeMedia({
      id: "vid-1",
      media_type: "VIDEO",
      video_url: "https://s3.example.com/video.mp4",
      captured_at: "2026-01-15T10:00:00Z",
    });
    mockedUseSnapshots.mockReturnValue({
      data: { items: [image], total: 1, offset: 0, limit: 3 },
    } as unknown as ReturnType<typeof useSnapshots>);
    mockedUseVideos.mockReturnValue({
      data: { items: [video], total: 1, offset: 0, limit: 3 },
    } as unknown as ReturnType<typeof useVideos>);

    render(<RecentMedia />);

    expect(screen.getByText("🎥")).toBeInTheDocument();
    expect(screen.getByText("📷")).toBeInTheDocument();
    expect(screen.getAllByRole("img")).toHaveLength(2);
  });

  it("falls back to a plain emoji icon for a video with no thumbnail", () => {
    const video = makeMedia({
      id: "vid-1",
      media_type: "VIDEO",
      thumbnail_url: "",
      video_url: "https://s3.example.com/video.mp4",
    });
    mockedUseSnapshots.mockReturnValue({
      data: { items: [], total: 0, offset: 0, limit: 3 },
    } as unknown as ReturnType<typeof useSnapshots>);
    mockedUseVideos.mockReturnValue({
      data: { items: [video], total: 1, offset: 0, limit: 3 },
    } as unknown as ReturnType<typeof useVideos>);

    render(<RecentMedia />);

    expect(screen.getByText("🎥")).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("opens the snapshot lightbox when an image is clicked", async () => {
    const image = makeMedia({ id: "img-1", media_type: "IMAGE" });
    mockedUseSnapshots.mockReturnValue({
      data: { items: [image], total: 1, offset: 0, limit: 3 },
    } as unknown as ReturnType<typeof useSnapshots>);
    mockedUseVideos.mockReturnValue({
      data: { items: [], total: 0, offset: 0, limit: 3 },
    } as unknown as ReturnType<typeof useVideos>);
    mockedUseSnapshot.mockReturnValue({ data: image, isLoading: false } as unknown as ReturnType<
      typeof useSnapshot
    >);

    const user = userEvent.setup();
    render(<RecentMedia />);

    await user.click(screen.getByRole("button"));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });
});
