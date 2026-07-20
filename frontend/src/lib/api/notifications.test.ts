import { describe, expect, it, vi } from "vitest";
import { getNotificationStatus, sendTestNotification } from "./notifications";
import { apiClient } from "./client";

vi.mock("./client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn() },
}));

describe("notifications api", () => {
  it("fetches /notifications/status", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: { providers: [] } });
    const result = await getNotificationStatus();
    expect(apiClient.get).toHaveBeenCalledWith("/notifications/status");
    expect(result).toEqual({ providers: [] });
  });

  it("posts to /notifications/test", async () => {
    const results = [{ provider: "telegram", success: true, duration_ms: 42, error_message: null }];
    vi.mocked(apiClient.post).mockResolvedValue({ data: results });
    const result = await sendTestNotification();
    expect(apiClient.post).toHaveBeenCalledWith("/notifications/test");
    expect(result).toEqual(results);
  });
});
