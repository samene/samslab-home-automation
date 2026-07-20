import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useDeleteVideo, useVideo } from "@/hooks/useVideos";
import type { SavedMediaDTO } from "@/types/api";
import { VideoLightbox } from "./VideoLightbox";

vi.mock("@/hooks/useVideos");

const mockedUseVideo = vi.mocked(useVideo);
const mockedUseDeleteVideo = vi.mocked(useDeleteVideo);

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

describe("VideoLightbox", () => {
  beforeEach(() => {
    mockedUseDeleteVideo.mockReturnValue({
      mutateAsync: vi.fn().mockResolvedValue(undefined),
      isPending: false,
    } as unknown as ReturnType<typeof useDeleteVideo>);
  });

  it("renders nothing open when videoId is null", () => {
    mockedUseVideo.mockReturnValue({ data: undefined, isLoading: false } as unknown as ReturnType<
      typeof useVideo
    >);
    render(<VideoLightbox videoId={null} onOpenChange={vi.fn()} />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("shows the video element and metadata once loaded", () => {
    mockedUseVideo.mockReturnValue({ data: VIDEO, isLoading: false } as unknown as ReturnType<
      typeof useVideo
    >);
    render(<VideoLightbox videoId="vid-1" onOpenChange={vi.fn()} />);

    expect(document.querySelector("video")).toHaveAttribute("src", "https://s3.example.com/clip.mp4");
    expect(screen.getByText("1920x1080")).toBeInTheDocument();
    expect(screen.getByText("1:05")).toBeInTheDocument();
  });

  it("uses the thumbnail as the video poster when one is available", () => {
    mockedUseVideo.mockReturnValue({
      data: { ...VIDEO, thumbnail_url: "https://s3.example.com/thumb.jpg" },
      isLoading: false,
    } as unknown as ReturnType<typeof useVideo>);
    render(<VideoLightbox videoId="vid-1" onOpenChange={vi.fn()} />);

    expect(document.querySelector("video")).toHaveAttribute("poster", "https://s3.example.com/thumb.jpg");
  });

  it("omits the poster attribute when no thumbnail is available", () => {
    mockedUseVideo.mockReturnValue({ data: VIDEO, isLoading: false } as unknown as ReturnType<
      typeof useVideo
    >);
    render(<VideoLightbox videoId="vid-1" onOpenChange={vi.fn()} />);

    expect(document.querySelector("video")).not.toHaveAttribute("poster");
  });

  it("provides a download link with the filename", () => {
    mockedUseVideo.mockReturnValue({ data: VIDEO, isLoading: false } as unknown as ReturnType<
      typeof useVideo
    >);
    render(<VideoLightbox videoId="vid-1" onOpenChange={vi.fn()} />);

    const link = screen.getByRole("link", { name: /download/i });
    expect(link).toHaveAttribute("href", "https://s3.example.com/clip.mp4");
    expect(link).toHaveAttribute("download", "clip.mp4");
  });

  it("deletes the video after confirming, and closes the lightbox", async () => {
    const mutateAsync = vi.fn().mockResolvedValue(undefined);
    mockedUseDeleteVideo.mockReturnValue({
      mutateAsync,
      isPending: false,
    } as unknown as ReturnType<typeof useDeleteVideo>);
    mockedUseVideo.mockReturnValue({ data: VIDEO, isLoading: false } as unknown as ReturnType<
      typeof useVideo
    >);
    const onOpenChange = vi.fn();
    const user = userEvent.setup();

    render(<VideoLightbox videoId="vid-1" onOpenChange={onOpenChange} />);

    await user.click(screen.getByRole("button", { name: /^delete$/i }));

    const dialog = await screen.findByRole("dialog", { name: /delete this video/i });
    expect(within(dialog).getByText(/clip\.mp4/)).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: /^delete$/i }));

    expect(mutateAsync).toHaveBeenCalledWith("vid-1");
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("shows a linked 'created by workflow' note when workflow_name is present", () => {
    mockedUseVideo.mockReturnValue({
      data: { ...VIDEO, workflow_id: "wf-1", workflow_name: "Nightly patrol" },
      isLoading: false,
    } as unknown as ReturnType<typeof useVideo>);

    render(
      <MemoryRouter>
        <VideoLightbox videoId="vid-1" onOpenChange={vi.fn()} />
      </MemoryRouter>,
    );

    const link = screen.getByRole("link", { name: "Nightly patrol" });
    expect(link).toHaveAttribute("href", "/workflows/wf-1/edit");
  });

  it("shows no workflow note when workflow_name is absent", () => {
    mockedUseVideo.mockReturnValue({ data: VIDEO, isLoading: false } as unknown as ReturnType<
      typeof useVideo
    >);

    render(<VideoLightbox videoId="vid-1" onOpenChange={vi.fn()} />);

    expect(screen.queryByText(/Created by workflow/)).not.toBeInTheDocument();
  });
});
