import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useDeleteSnapshot, useSnapshot } from "@/hooks/useSnapshots";
import type { SavedMediaDTO } from "@/types/api";
import { SnapshotLightbox } from "./SnapshotLightbox";

vi.mock("@/hooks/useSnapshots");

const mockedUseSnapshot = vi.mocked(useSnapshot);
const mockedUseDeleteSnapshot = vi.mocked(useDeleteSnapshot);

const SNAPSHOT: SavedMediaDTO = {
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
};

describe("SnapshotLightbox", () => {
  beforeEach(() => {
    mockedUseDeleteSnapshot.mockReturnValue({
      mutateAsync: vi.fn().mockResolvedValue(undefined),
      isPending: false,
    } as unknown as ReturnType<typeof useDeleteSnapshot>);
  });

  it("renders nothing open when snapshotId is null", () => {
    mockedUseSnapshot.mockReturnValue({ data: undefined, isLoading: false } as unknown as ReturnType<
      typeof useSnapshot
    >);
    render(<SnapshotLightbox snapshotId={null} onOpenChange={vi.fn()} />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("shows the full image and metadata once loaded", () => {
    mockedUseSnapshot.mockReturnValue({ data: SNAPSHOT, isLoading: false } as unknown as ReturnType<
      typeof useSnapshot
    >);
    render(<SnapshotLightbox snapshotId="snap-1" onOpenChange={vi.fn()} />);

    expect(screen.getByRole("img", { name: "snap-1.jpg" })).toHaveAttribute(
      "src",
      "https://s3.example.com/full.jpg",
    );
    expect(screen.getByText("1920x1080")).toBeInTheDocument();
    expect(screen.getByText("200 KB")).toBeInTheDocument();
  });

  it("provides a download link with the filename", () => {
    mockedUseSnapshot.mockReturnValue({ data: SNAPSHOT, isLoading: false } as unknown as ReturnType<
      typeof useSnapshot
    >);
    render(<SnapshotLightbox snapshotId="snap-1" onOpenChange={vi.fn()} />);

    const link = screen.getByRole("link", { name: /download/i });
    expect(link).toHaveAttribute("href", "https://s3.example.com/full.jpg");
    expect(link).toHaveAttribute("download", "snap-1.jpg");
  });

  it("deletes the snapshot after confirming, and closes the lightbox", async () => {
    const mutateAsync = vi.fn().mockResolvedValue(undefined);
    mockedUseDeleteSnapshot.mockReturnValue({
      mutateAsync,
      isPending: false,
    } as unknown as ReturnType<typeof useDeleteSnapshot>);
    mockedUseSnapshot.mockReturnValue({ data: SNAPSHOT, isLoading: false } as unknown as ReturnType<
      typeof useSnapshot
    >);
    const onOpenChange = vi.fn();
    const user = userEvent.setup();

    render(<SnapshotLightbox snapshotId="snap-1" onOpenChange={onOpenChange} />);

    await user.click(screen.getByRole("button", { name: /^delete$/i }));

    const dialog = await screen.findByRole("dialog", { name: /delete this snapshot/i });
    expect(within(dialog).getByText(/snap-1\.jpg/)).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: /^delete$/i }));

    expect(mutateAsync).toHaveBeenCalledWith("snap-1");
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("shows a linked 'created by workflow' note when workflow_name is present", () => {
    mockedUseSnapshot.mockReturnValue({
      data: { ...SNAPSHOT, workflow_id: "wf-1", workflow_name: "Nightly patrol" },
      isLoading: false,
    } as unknown as ReturnType<typeof useSnapshot>);

    render(
      <MemoryRouter>
        <SnapshotLightbox snapshotId="snap-1" onOpenChange={vi.fn()} />
      </MemoryRouter>,
    );

    const link = screen.getByRole("link", { name: "Nightly patrol" });
    expect(link).toHaveAttribute("href", "/workflows/wf-1/edit");
  });

  it("shows no workflow note when workflow_name is absent", () => {
    mockedUseSnapshot.mockReturnValue({ data: SNAPSHOT, isLoading: false } as unknown as ReturnType<
      typeof useSnapshot
    >);

    render(<SnapshotLightbox snapshotId="snap-1" onOpenChange={vi.fn()} />);

    expect(screen.queryByText(/Created by workflow/)).not.toBeInTheDocument();
  });
});
