import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { toast } from "sonner";
import { describe, expect, it, vi } from "vitest";
import * as commandsApi from "@/lib/api/commands";
import type { CommandDetailDTO, CommandPageDTO } from "@/types/api";
import { useCancelCommand, useCommand, useCommands, useCreateCommand } from "./useCommands";

vi.mock("@/lib/api/commands");
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const COMMAND: CommandDetailDTO = {
  id: "cmd-1",
  device_id: "device-1",
  command_type: "pump.start",
  status: "COMPLETED",
  priority: "NORMAL",
  payload: {},
  requested_by: null,
  created_at: "2026-01-15T10:00:00Z",
  scheduled_at: null,
  started_at: null,
  completed_at: null,
  expires_at: null,
  correlation_id: "corr-1",
  trace_id: null,
  retry_count: 0,
  max_retries: 3,
  result: null,
  events: [],
};

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

describe("useCommands", () => {
  it("fetches the command list", async () => {
    const page: CommandPageDTO = { items: [COMMAND], total: 1, offset: 0, limit: 50 };
    vi.mocked(commandsApi.listCommands).mockResolvedValue(page);

    const { result } = renderHook(() => useCommands(), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(page);
  });
});

describe("useCommand", () => {
  it("skips fetching without a commandId", () => {
    const { result } = renderHook(() => useCommand(undefined), { wrapper });
    expect(result.current.fetchStatus).toBe("idle");
  });

  it("fetches the detail once a commandId is given", async () => {
    vi.mocked(commandsApi.getCommand).mockResolvedValue(COMMAND);
    const { result } = renderHook(() => useCommand("cmd-1"), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(commandsApi.getCommand).toHaveBeenCalledWith("cmd-1");
  });
});

describe("useCreateCommand", () => {
  it("creates a command and shows a success toast", async () => {
    vi.mocked(commandsApi.createCommand).mockResolvedValue(COMMAND);
    const { result } = renderHook(() => useCreateCommand(), { wrapper });

    result.current.mutate({ device_id: "device-1", command_type: "pump.start" });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(toast.success).toHaveBeenCalledWith("pump.start sent");
  });

  it("shows an error toast when creation fails", async () => {
    vi.mocked(commandsApi.createCommand).mockRejectedValue(new Error("boom"));
    const { result } = renderHook(() => useCreateCommand(), { wrapper });

    result.current.mutate({ device_id: "device-1", command_type: "pump.start" });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(toast.error).toHaveBeenCalledWith("boom");
  });
});

describe("useCancelCommand", () => {
  it("cancels a command and shows a success toast", async () => {
    vi.mocked(commandsApi.cancelCommand).mockResolvedValue(COMMAND);
    const { result } = renderHook(() => useCancelCommand(), { wrapper });

    result.current.mutate({ commandId: "cmd-1", reason: "no longer needed" });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(commandsApi.cancelCommand).toHaveBeenCalledWith("cmd-1", "no longer needed");
    expect(toast.success).toHaveBeenCalledWith("Command cancelled");
  });
});
