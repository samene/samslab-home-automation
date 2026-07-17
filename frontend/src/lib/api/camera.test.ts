import { describe, expect, it, vi } from "vitest";
import { getCameraStatus, startCameraStream, stopCameraStream } from "./camera";
import { apiClient } from "./client";

vi.mock("./client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn() },
}));

describe("camera api", () => {
  it("posts to /camera/start", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ data: { running: true } });
    const result = await startCameraStream();
    expect(apiClient.post).toHaveBeenCalledWith("/camera/start");
    expect(result).toEqual({ running: true });
  });

  it("posts to /camera/stop", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ data: { status: "stopped" } });
    const result = await stopCameraStream();
    expect(apiClient.post).toHaveBeenCalledWith("/camera/stop");
    expect(result).toEqual({ status: "stopped" });
  });

  it("fetches /camera/status", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: { running: false } });
    const result = await getCameraStatus();
    expect(apiClient.get).toHaveBeenCalledWith("/camera/status");
    expect(result).toEqual({ running: false });
  });
});
