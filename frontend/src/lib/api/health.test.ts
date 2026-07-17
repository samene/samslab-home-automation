import { describe, expect, it, vi } from "vitest";
import { getServiceInfo } from "./health";
import { apiClient } from "./client";

vi.mock("./client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn() },
}));

describe("health api", () => {
  it("fetches service info from /", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: { status: "ok", service: "samslab-cloud" } });
    const result = await getServiceInfo();
    expect(apiClient.get).toHaveBeenCalledWith("/");
    expect(result.status).toBe("ok");
  });
});
