import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { SavedMediaDTO } from "@/types/api";
import { VideoCard } from "./VideoCard";

function makeVideo(overrides: Partial<SavedMediaDTO> = {}): SavedMediaDTO {
  return {
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
    ...overrides,
  };
}

describe("VideoCard", () => {
  it("renders the device name, resolution, and file size", () => {
    render(<VideoCard video={makeVideo()} deviceName="Backyard Pi" onClick={vi.fn()} />);

    expect(screen.getByText("Backyard Pi")).toBeInTheDocument();
    expect(screen.getByText("1920x1080 · 10.0 MB")).toBeInTheDocument();
  });

  it("renders the duration badge as mm:ss", () => {
    render(<VideoCard video={makeVideo({ duration: 65 })} deviceName="Backyard Pi" onClick={vi.fn()} />);

    expect(screen.getByText("1:05")).toBeInTheDocument();
  });

  it("omits the duration badge when duration is null", () => {
    render(<VideoCard video={makeVideo({ duration: null })} deviceName="Backyard Pi" onClick={vi.fn()} />);

    expect(screen.queryByText(/^\d+:\d{2}$/)).not.toBeInTheDocument();
  });

  it("renders the thumbnail image when one is available", () => {
    render(
      <VideoCard
        video={makeVideo({ thumbnail_url: "https://s3.example.com/thumb.jpg" })}
        deviceName="Backyard Pi"
        onClick={vi.fn()}
      />,
    );

    expect(screen.getByRole("img")).toHaveAttribute("src", "https://s3.example.com/thumb.jpg");
  });

  it("falls back to a placeholder icon when no thumbnail is available", () => {
    render(<VideoCard video={makeVideo({ thumbnail_url: "" })} deviceName="Backyard Pi" onClick={vi.fn()} />);

    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("calls onClick when the card is clicked", async () => {
    const onClick = vi.fn();
    const user = userEvent.setup();
    render(<VideoCard video={makeVideo()} deviceName="Backyard Pi" onClick={onClick} />);

    await user.click(screen.getByRole("button"));
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("shows a 'created by workflow' note when workflow_name is present", () => {
    render(
      <VideoCard
        video={makeVideo({ workflow_id: "wf-1", workflow_name: "Nightly patrol" })}
        deviceName="Backyard Pi"
        onClick={vi.fn()}
      />,
    );

    expect(screen.getByText(/Created by workflow/)).toBeInTheDocument();
    expect(screen.getByText(/Nightly patrol/)).toBeInTheDocument();
  });
});
