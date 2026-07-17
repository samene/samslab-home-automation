import { describe, expect, it, vi } from "vitest";
import { cancelCommand, createCommand, getCommand, listCommands } from "./commands";
import { apiClient } from "./client";

vi.mock("./client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn() },
}));

describe("commands api", () => {
  it("lists commands with the given params", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: { items: [], total: 0, offset: 0, limit: 50 } });
    await listCommands({ device: "device-1", status: "PENDING" });
    expect(apiClient.get).toHaveBeenCalledWith("/commands", {
      params: { device: "device-1", status: "PENDING" },
    });
  });

  it("fetches a single command detail", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: { id: "cmd-1" } });
    const result = await getCommand("cmd-1");
    expect(apiClient.get).toHaveBeenCalledWith("/commands/cmd-1");
    expect(result).toEqual({ id: "cmd-1" });
  });

  it("creates a command", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ data: { id: "cmd-1" } });
    const request = { device_id: "device-1", command_type: "pump.start" };
    await createCommand(request);
    expect(apiClient.post).toHaveBeenCalledWith("/commands", request);
  });

  it("cancels a command with an optional reason", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ data: { id: "cmd-1" } });
    await cancelCommand("cmd-1", "no longer needed");
    expect(apiClient.post).toHaveBeenCalledWith("/commands/cmd-1/cancel", {
      reason: "no longer needed",
    });
  });
});
