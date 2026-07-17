import { describe, expect, it, vi } from "vitest";
import { getCurrentUser, login, logout } from "./auth";
import { apiClient } from "./client";

vi.mock("./client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn() },
}));

describe("auth api", () => {
  it("posts credentials to /auth/login", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({
      data: { access_token: "a", refresh_token: "b", token_type: "bearer", expires_in: 900 },
    });
    const result = await login({ username: "sam", password: "secret" });
    expect(apiClient.post).toHaveBeenCalledWith("/auth/login", { username: "sam", password: "secret" });
    expect(result.access_token).toBe("a");
  });

  it("posts the refresh token to /auth/logout", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ data: undefined });
    await logout("refresh-token");
    expect(apiClient.post).toHaveBeenCalledWith("/auth/logout", { refresh_token: "refresh-token" });
  });

  it("fetches the current user from /auth/me", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      data: { id: "1", username: "sam" },
    });
    const result = await getCurrentUser();
    expect(apiClient.get).toHaveBeenCalledWith("/auth/me");
    expect(result.username).toBe("sam");
  });
});
