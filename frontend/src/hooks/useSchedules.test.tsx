import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { toast } from "sonner";
import { describe, expect, it, vi } from "vitest";
import * as schedulesApi from "@/lib/api/schedules";
import type { ScheduleDTO, SchedulePageDTO } from "@/types/api";
import {
  getScheduleRefetchInterval,
  useCreateSchedule,
  useDeleteSchedule,
  useDisableSchedule,
  useEnableSchedule,
  useRunScheduleNow,
  useSchedule,
  useSchedules,
  useScheduleExecutions,
  useUpdateSchedule,
} from "./useSchedules";

vi.mock("@/lib/api/schedules");
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const SCHEDULE: ScheduleDTO = {
  id: "sched-1",
  workflow_id: "wf-1",
  workflow_name: "Nightly patrol",
  name: "Every five minutes",
  description: "Runs often",
  enabled: true,
  schedule_type: "CRON",
  cron_expression: "*/5 * * * *",
  run_at: null,
  timezone: "UTC",
  run_count: 3,
  last_run_at: "2026-01-15T10:00:00Z",
  next_run_at: "2026-01-15T10:05:00Z",
  last_status: "COMPLETED",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

describe("useSchedules", () => {
  it("fetches the schedule list", async () => {
    const page: SchedulePageDTO = { items: [SCHEDULE], total: 1, offset: 0, limit: 20 };
    vi.mocked(schedulesApi.listSchedules).mockResolvedValue(page);

    const { result } = renderHook(() => useSchedules(), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(page);
  });
});

describe("useSchedule", () => {
  it("skips fetching without an id", () => {
    const { result } = renderHook(() => useSchedule(undefined), { wrapper });
    expect(result.current.fetchStatus).toBe("idle");
    expect(schedulesApi.getSchedule).not.toHaveBeenCalled();
  });

  it("fetches the schedule once an id is given", async () => {
    vi.mocked(schedulesApi.getSchedule).mockResolvedValue(SCHEDULE);
    const { result } = renderHook(() => useSchedule("sched-1"), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(schedulesApi.getSchedule).toHaveBeenCalledWith("sched-1");
  });

  it("polls every 2s while last_status is RUNNING, and stops once it settles", async () => {
    vi.useFakeTimers();
    try {
      vi.mocked(schedulesApi.getSchedule).mockResolvedValue({ ...SCHEDULE, last_status: "RUNNING" });

      const { result } = renderHook(() => useSchedule("sched-1"), { wrapper });

      await act(async () => {
        await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));
      });
      const callsAfterInitialFetch = vi.mocked(schedulesApi.getSchedule).mock.calls.length;
      expect(callsAfterInitialFetch).toBeGreaterThanOrEqual(1);

      await act(async () => {
        await vi.advanceTimersByTimeAsync(2000);
      });
      expect(vi.mocked(schedulesApi.getSchedule).mock.calls.length).toBeGreaterThan(
        callsAfterInitialFetch,
      );
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("getScheduleRefetchInterval", () => {
  it("returns 2000ms while last_status is RUNNING", () => {
    expect(getScheduleRefetchInterval({ ...SCHEDULE, last_status: "RUNNING" })).toBe(2000);
  });

  it("returns false once last_status has settled", () => {
    expect(getScheduleRefetchInterval({ ...SCHEDULE, last_status: "COMPLETED" })).toBe(false);
  });

  it("returns false when last_status is null", () => {
    expect(getScheduleRefetchInterval({ ...SCHEDULE, last_status: null })).toBe(false);
  });

  it("returns false when data hasn't loaded yet", () => {
    expect(getScheduleRefetchInterval(undefined)).toBe(false);
  });
});

describe("useCreateSchedule", () => {
  it("creates a schedule and shows a success toast", async () => {
    vi.mocked(schedulesApi.createSchedule).mockResolvedValue(SCHEDULE);
    const { result } = renderHook(() => useCreateSchedule(), { wrapper });

    result.current.mutate({
      workflow_id: "wf-1",
      name: "Every five minutes",
      schedule_type: "CRON",
      cron_expression: "*/5 * * * *",
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(toast.success).toHaveBeenCalledWith("Schedule created");
  });

  it("shows an error toast when creation fails", async () => {
    vi.mocked(schedulesApi.createSchedule).mockRejectedValue(new Error("invalid cron"));
    const { result } = renderHook(() => useCreateSchedule(), { wrapper });

    result.current.mutate({
      workflow_id: "wf-1",
      name: "Bad",
      schedule_type: "CRON",
      cron_expression: "not a cron",
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(toast.error).toHaveBeenCalledWith("invalid cron");
  });
});

describe("useUpdateSchedule", () => {
  it("updates a schedule and shows a success toast", async () => {
    vi.mocked(schedulesApi.updateSchedule).mockResolvedValue(SCHEDULE);
    const { result } = renderHook(() => useUpdateSchedule(), { wrapper });

    result.current.mutate({
      id: "sched-1",
      request: { workflow_id: "wf-1", name: "Renamed", schedule_type: "CRON", cron_expression: "0 0 * * *" },
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(schedulesApi.updateSchedule).toHaveBeenCalledWith("sched-1", {
      workflow_id: "wf-1",
      name: "Renamed",
      schedule_type: "CRON",
      cron_expression: "0 0 * * *",
    });
    expect(toast.success).toHaveBeenCalledWith("Schedule updated");
  });
});

describe("useDeleteSchedule", () => {
  it("deletes a schedule and shows a success toast", async () => {
    vi.mocked(schedulesApi.deleteSchedule).mockResolvedValue(undefined);
    const { result } = renderHook(() => useDeleteSchedule(), { wrapper });

    result.current.mutate({ id: "sched-1" });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(schedulesApi.deleteSchedule).toHaveBeenCalledWith("sched-1", { deleteArtifacts: undefined });
    expect(toast.success).toHaveBeenCalledWith("Schedule deleted");
  });

  it("passes deleteArtifacts through to the API call", async () => {
    vi.mocked(schedulesApi.deleteSchedule).mockResolvedValue(undefined);
    const { result } = renderHook(() => useDeleteSchedule(), { wrapper });

    result.current.mutate({ id: "sched-1", deleteArtifacts: true });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(schedulesApi.deleteSchedule).toHaveBeenCalledWith("sched-1", { deleteArtifacts: true });
  });
});

describe("useRunScheduleNow", () => {
  it("triggers the workflow and shows a 'started' toast", async () => {
    vi.mocked(schedulesApi.runScheduleNow).mockResolvedValue({
      id: "wf-1",
      name: "Nightly patrol",
      description: null,
      enabled: true,
      run_count: 1,
      last_run_at: null,
      last_run_status: null,
      last_run_duration_ms: null,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
      steps: [],
      latest_run: null,
    });
    const { result } = renderHook(() => useRunScheduleNow(), { wrapper });

    result.current.mutate("sched-1");

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(toast.success).toHaveBeenCalledWith("Workflow started");
  });
});

describe("useEnableSchedule", () => {
  it("enables a schedule and shows a success toast", async () => {
    vi.mocked(schedulesApi.enableSchedule).mockResolvedValue(SCHEDULE);
    const { result } = renderHook(() => useEnableSchedule(), { wrapper });

    result.current.mutate("sched-1");

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(toast.success).toHaveBeenCalledWith("Schedule enabled");
  });
});

describe("useDisableSchedule", () => {
  it("disables a schedule and shows a success toast", async () => {
    vi.mocked(schedulesApi.disableSchedule).mockResolvedValue({ ...SCHEDULE, enabled: false });
    const { result } = renderHook(() => useDisableSchedule(), { wrapper });

    result.current.mutate("sched-1");

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(toast.success).toHaveBeenCalledWith("Schedule disabled");
  });
});

describe("useScheduleExecutions", () => {
  it("fetches the executions list", async () => {
    vi.mocked(schedulesApi.listScheduleExecutions).mockResolvedValue({
      items: [],
      total: 0,
      offset: 0,
      limit: 100,
    });
    const { result } = renderHook(() => useScheduleExecutions(), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(schedulesApi.listScheduleExecutions).toHaveBeenCalledWith({});
  });
});
