import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useDevices } from "@/hooks/useDevices";
import { useDeleteSnapshot, useSnapshot, useSnapshots } from "@/hooks/useSnapshots";
import { useDeleteVideo, useVideo, useVideos } from "@/hooks/useVideos";
import type { DevicePageDTO, SavedMediaDTO } from "@/types/api";
import { SavedMediaPage } from "./SavedMediaPage";

vi.mock("@/hooks/useDevices");
vi.mock("@/hooks/useSnapshots");
vi.mock("@/hooks/useVideos");

const mockedUseDevices = vi.mocked(useDevices);
const mockedUseSnapshots = vi.mocked(useSnapshots);
const mockedUseSnapshot = vi.mocked(useSnapshot);
const mockedUseDeleteSnapshot = vi.mocked(useDeleteSnapshot);
const mockedUseVideos = vi.mocked(useVideos);
const mockedUseVideo = vi.mocked(useVideo);
const mockedUseDeleteVideo = vi.mocked(useDeleteVideo);

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

describe("SavedMediaPage", () => {
  beforeEach(() => {
    mockedUseDevices.mockReturnValue({ data: DEVICES } as unknown as ReturnType<typeof useDevices>);
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
    mockedUseVideos.mockReturnValue({
      data: { items: [], total: 0, offset: 0, limit: 200 },
      isLoading: false,
    } as unknown as ReturnType<typeof useVideos>);
  });

  it("shows an empty state on the Images tab when there are no images", () => {
    mockedUseSnapshots.mockReturnValue({
      data: { items: [], total: 0, offset: 0, limit: 200 },
      isLoading: false,
    } as unknown as ReturnType<typeof useSnapshots>);

    render(<SavedMediaPage />);

    expect(screen.getByText("No images yet.")).toBeInTheDocument();
  });

  it("shows an error state on the Images tab instead of silently rendering empty", () => {
    mockedUseSnapshots.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
    } as unknown as ReturnType<typeof useSnapshots>);

    render(<SavedMediaPage />);

    expect(screen.getByText("Failed to load images.")).toBeInTheDocument();
    expect(screen.queryByText("No images yet.")).not.toBeInTheDocument();
  });

  it("shows an error state on the Videos tab instead of silently rendering empty", async () => {
    mockedUseSnapshots.mockReturnValue({
      data: { items: [], total: 0, offset: 0, limit: 100 },
      isLoading: false,
    } as unknown as ReturnType<typeof useSnapshots>);
    mockedUseVideos.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
    } as unknown as ReturnType<typeof useVideos>);

    const user = userEvent.setup();
    render(<SavedMediaPage />);

    await user.click(screen.getByRole("tab", { name: "Videos" }));

    expect(screen.getByText("Failed to load videos.")).toBeInTheDocument();
    expect(screen.queryByText("No videos yet.")).not.toBeInTheDocument();
  });

  it("groups images by day and opens the lightbox on card click", async () => {
    mockedUseSnapshots.mockReturnValue({
      data: { items: [makeMedia()], total: 1, offset: 0, limit: 200 },
      isLoading: false,
    } as unknown as ReturnType<typeof useSnapshots>);
    mockedUseSnapshot.mockReturnValue({ data: makeMedia(), isLoading: false } as unknown as ReturnType<
      typeof useSnapshot
    >);

    const user = userEvent.setup();
    render(<SavedMediaPage />);

    expect(screen.getAllByText("Backyard Pi")).toHaveLength(1);
    await user.click(screen.getByRole("img"));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });

  it("switches to the Videos tab and shows an empty state when there are no videos", async () => {
    mockedUseSnapshots.mockReturnValue({
      data: { items: [], total: 0, offset: 0, limit: 200 },
      isLoading: false,
    } as unknown as ReturnType<typeof useSnapshots>);

    const user = userEvent.setup();
    render(<SavedMediaPage />);

    await user.click(screen.getByRole("tab", { name: "Videos" }));

    expect(screen.getByText("No videos yet.")).toBeInTheDocument();
  });

  it("shows video cards on the Videos tab", async () => {
    mockedUseSnapshots.mockReturnValue({
      data: { items: [], total: 0, offset: 0, limit: 200 },
      isLoading: false,
    } as unknown as ReturnType<typeof useSnapshots>);
    mockedUseVideos.mockReturnValue({
      data: {
        items: [
          makeMedia({
            id: "vid-1",
            media_type: "VIDEO",
            filename: "clip.mp4",
            video_url: "https://s3.example.com/clip.mp4",
            duration: 65,
          }),
        ],
        total: 1,
        offset: 0,
        limit: 200,
      },
      isLoading: false,
    } as unknown as ReturnType<typeof useVideos>);

    const user = userEvent.setup();
    render(<SavedMediaPage />);

    await user.click(screen.getByRole("tab", { name: "Videos" }));

    expect(screen.getByText("1:05")).toBeInTheDocument();
  });
});
