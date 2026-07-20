import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { SavedMediaDTO } from "@/types/api";
import { SnapshotCard } from "./SnapshotCard";

function makeSnapshot(overrides: Partial<SavedMediaDTO> = {}): SavedMediaDTO {
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

describe("SnapshotCard", () => {
  it("renders the device name, resolution, and file size", () => {
    render(
      <SnapshotCard snapshot={makeSnapshot()} deviceName="Backyard Pi" onClick={vi.fn()} />,
    );

    expect(screen.getByText("Backyard Pi")).toBeInTheDocument();
    expect(screen.getByText("1920x1080 · 200 KB")).toBeInTheDocument();
  });

  it("renders the thumbnail image", () => {
    render(
      <SnapshotCard snapshot={makeSnapshot()} deviceName="Backyard Pi" onClick={vi.fn()} />,
    );

    expect(screen.getByRole("img")).toHaveAttribute("src", "https://s3.example.com/thumb.jpg");
  });

  it("calls onClick when the card is clicked", async () => {
    const onClick = vi.fn();
    const user = userEvent.setup();
    render(<SnapshotCard snapshot={makeSnapshot()} deviceName="Backyard Pi" onClick={onClick} />);

    await user.click(screen.getByRole("button"));
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("shows a 'created by workflow' note when workflow_name is present", () => {
    render(
      <SnapshotCard
        snapshot={makeSnapshot({ workflow_id: "wf-1", workflow_name: "Nightly patrol" })}
        deviceName="Backyard Pi"
        onClick={vi.fn()}
      />,
    );

    expect(screen.getByText(/Created by workflow/)).toBeInTheDocument();
    expect(screen.getByText(/Nightly patrol/)).toBeInTheDocument();
  });

  it("shows no workflow note when workflow_name is absent", () => {
    render(
      <SnapshotCard snapshot={makeSnapshot()} deviceName="Backyard Pi" onClick={vi.fn()} />,
    );

    expect(screen.queryByText(/Created by workflow/)).not.toBeInTheDocument();
  });
});
