import { describe, expect, it, vi } from "vitest";
import { getDevice, listDevices } from "./devices";
import { apiClient } from "./client";

vi.mock("./client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn() },
}));

describe("devices api", () => {
  it("lists devices with the given params", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: { items: [], total: 0, offset: 0, limit: 50 } });
    await listDevices({ limit: 10 });
    expect(apiClient.get).toHaveBeenCalledWith("/devices", { params: { limit: 10 } });
  });

  it("fetches a single device by id", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: { id: "device-1" } });
    const result = await getDevice("device-1");
    expect(apiClient.get).toHaveBeenCalledWith("/devices/device-1");
    expect(result).toEqual({ id: "device-1" });
  });
});
