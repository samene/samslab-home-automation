import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { toast } from "sonner";
import { describe, expect, it, vi } from "vitest";
import * as workflowsApi from "@/lib/api/workflows";
import type { WorkflowDetailDTO, WorkflowDTO, WorkflowPageDTO } from "@/types/api";
import {
  getWorkflowRefetchInterval,
  useCreateWorkflow,
  useDeleteWorkflow,
  useDuplicateWorkflow,
  useRunWorkflow,
  useUpdateWorkflow,
  useWorkflow,
  useWorkflows,
} from "./useWorkflows";

vi.mock("@/lib/api/workflows");
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const WORKFLOW: WorkflowDTO = {
  id: "wf-1",
  name: "Morning Watering",
  description: "Waters the garden",
  enabled: true,
  run_count: 3,
  last_run_at: "2026-01-15T10:00:00Z",
  last_run_status: "COMPLETED",
  last_run_duration_ms: 4200,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const WORKFLOW_DETAIL: WorkflowDetailDTO = {
  ...WORKFLOW,
  steps: [
    {
      id: "step-1",
      step_type: "COMMAND",
      command_type: "camera.snapshot",
      sleep_seconds: null,
      group_mode: null,
      children: [],
    },
    {
      id: "step-2",
      step_type: "GROUP",
      command_type: null,
      sleep_seconds: null,
      group_mode: "PARALLEL",
      children: [
        {
          id: "step-2a",
          step_type: "SLEEP",
          command_type: null,
          sleep_seconds: 5,
          group_mode: null,
          children: [],
        },
      ],
    },
  ],
  latest_run: null,
};

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

describe("useWorkflows", () => {
  it("fetches the workflow list", async () => {
    const page: WorkflowPageDTO = { items: [WORKFLOW], total: 1, offset: 0, limit: 20 };
    vi.mocked(workflowsApi.listWorkflows).mockResolvedValue(page);

    const { result } = renderHook(() => useWorkflows(), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(page);
  });
});

describe("useWorkflow", () => {
  it("skips fetching without an id", () => {
    const { result } = renderHook(() => useWorkflow(undefined), { wrapper });
    expect(result.current.fetchStatus).toBe("idle");
    expect(workflowsApi.getWorkflow).not.toHaveBeenCalled();
  });

  it("fetches the detail once an id is given", async () => {
    vi.mocked(workflowsApi.getWorkflow).mockResolvedValue(WORKFLOW_DETAIL);
    const { result } = renderHook(() => useWorkflow("wf-1"), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(workflowsApi.getWorkflow).toHaveBeenCalledWith("wf-1");
  });

  it("polls every 2s while the latest run is RUNNING, and stops once it settles", async () => {
    vi.useFakeTimers();
    try {
      const runningDetail: WorkflowDetailDTO = {
        ...WORKFLOW_DETAIL,
        latest_run: {
          id: "run-1",
          workflow_id: "wf-1",
          status: "RUNNING",
          started_at: "2026-01-15T10:00:00Z",
          completed_at: null,
          error_message: null,
          step_runs: [],
        },
      };
      vi.mocked(workflowsApi.getWorkflow).mockResolvedValue(runningDetail);

      const { result } = renderHook(() => useWorkflow("wf-1"), { wrapper });

      await act(async () => {
        await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));
      });
      const callsAfterInitialFetch = vi.mocked(workflowsApi.getWorkflow).mock.calls.length;
      expect(callsAfterInitialFetch).toBeGreaterThanOrEqual(1);

      await act(async () => {
        await vi.advanceTimersByTimeAsync(2000);
      });
      expect(vi.mocked(workflowsApi.getWorkflow).mock.calls.length).toBeGreaterThan(
        callsAfterInitialFetch,
      );
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("getWorkflowRefetchInterval", () => {
  it("returns 2000ms while the latest run is RUNNING", () => {
    expect(
      getWorkflowRefetchInterval({
        ...WORKFLOW_DETAIL,
        latest_run: {
          id: "run-1",
          workflow_id: "wf-1",
          status: "RUNNING",
          started_at: "2026-01-15T10:00:00Z",
          completed_at: null,
          error_message: null,
          step_runs: [],
        },
      }),
    ).toBe(2000);
  });

  it("returns false when there is no latest run", () => {
    expect(getWorkflowRefetchInterval(WORKFLOW_DETAIL)).toBe(false);
  });

  it("returns false once the latest run has settled", () => {
    expect(
      getWorkflowRefetchInterval({
        ...WORKFLOW_DETAIL,
        latest_run: {
          id: "run-1",
          workflow_id: "wf-1",
          status: "COMPLETED",
          started_at: "2026-01-15T10:00:00Z",
          completed_at: "2026-01-15T10:00:05Z",
          error_message: null,
          step_runs: [],
        },
      }),
    ).toBe(false);
  });

  it("returns false when data hasn't loaded yet", () => {
    expect(getWorkflowRefetchInterval(undefined)).toBe(false);
  });
});

describe("useCreateWorkflow", () => {
  it("creates a workflow and shows a success toast", async () => {
    vi.mocked(workflowsApi.createWorkflow).mockResolvedValue(WORKFLOW_DETAIL);
    const { result } = renderHook(() => useCreateWorkflow(), { wrapper });

    result.current.mutate({ name: "Morning Watering", steps: [] });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(toast.success).toHaveBeenCalledWith("Workflow created");
  });

  it("shows an error toast when creation fails", async () => {
    vi.mocked(workflowsApi.createWorkflow).mockRejectedValue(new Error("invalid"));
    const { result } = renderHook(() => useCreateWorkflow(), { wrapper });

    result.current.mutate({ name: "", steps: [] });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(toast.error).toHaveBeenCalledWith("invalid");
  });
});

describe("useUpdateWorkflow", () => {
  it("updates a workflow and shows a success toast", async () => {
    vi.mocked(workflowsApi.updateWorkflow).mockResolvedValue(WORKFLOW_DETAIL);
    const { result } = renderHook(() => useUpdateWorkflow(), { wrapper });

    result.current.mutate({ id: "wf-1", request: { name: "Morning Watering", steps: [] } });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(workflowsApi.updateWorkflow).toHaveBeenCalledWith("wf-1", {
      name: "Morning Watering",
      steps: [],
    });
    expect(toast.success).toHaveBeenCalledWith("Workflow updated");
  });
});

describe("useDeleteWorkflow", () => {
  it("deletes a workflow and shows a success toast", async () => {
    vi.mocked(workflowsApi.deleteWorkflow).mockResolvedValue(undefined);
    const { result } = renderHook(() => useDeleteWorkflow(), { wrapper });

    result.current.mutate({ id: "wf-1" });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(workflowsApi.deleteWorkflow).toHaveBeenCalledWith("wf-1", { deleteArtifacts: undefined });
    expect(toast.success).toHaveBeenCalledWith("Workflow deleted");
  });

  it("passes deleteArtifacts through to the API call", async () => {
    vi.mocked(workflowsApi.deleteWorkflow).mockResolvedValue(undefined);
    const { result } = renderHook(() => useDeleteWorkflow(), { wrapper });

    result.current.mutate({ id: "wf-1", deleteArtifacts: true });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(workflowsApi.deleteWorkflow).toHaveBeenCalledWith("wf-1", { deleteArtifacts: true });
  });
});

describe("useRunWorkflow", () => {
  it("starts a workflow run and shows a 'started' toast, not 'completed'", async () => {
    vi.mocked(workflowsApi.runWorkflow).mockResolvedValue({
      id: "run-1",
      workflow_id: "wf-1",
      status: "RUNNING",
      started_at: "2026-01-15T10:00:00Z",
      completed_at: null,
      error_message: null,
      step_runs: [],
    });
    const { result } = renderHook(() => useRunWorkflow(), { wrapper });

    result.current.mutate("wf-1");

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(toast.success).toHaveBeenCalledWith("Workflow started");
  });

  it("shows an error toast when starting a run fails", async () => {
    vi.mocked(workflowsApi.runWorkflow).mockRejectedValue(new Error("workflow disabled"));
    const { result } = renderHook(() => useRunWorkflow(), { wrapper });

    result.current.mutate("wf-1");

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(toast.error).toHaveBeenCalledWith("workflow disabled");
  });
});

describe("useDuplicateWorkflow", () => {
  it("fetches the workflow and re-creates it with the same steps, stripped of ids", async () => {
    vi.mocked(workflowsApi.getWorkflow).mockResolvedValue(WORKFLOW_DETAIL);
    vi.mocked(workflowsApi.createWorkflow).mockResolvedValue(WORKFLOW_DETAIL);
    const { result } = renderHook(() => useDuplicateWorkflow(), { wrapper });

    result.current.mutate("wf-1");

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(workflowsApi.getWorkflow).toHaveBeenCalledWith("wf-1");
    expect(workflowsApi.createWorkflow).toHaveBeenCalledWith({
      name: "Morning Watering (Copy)",
      description: "Waters the garden",
      enabled: true,
      steps: [
        {
          step_type: "COMMAND",
          command_type: "camera.snapshot",
          sleep_seconds: null,
          group_mode: null,
          children: [],
        },
        {
          step_type: "GROUP",
          command_type: null,
          sleep_seconds: null,
          group_mode: "PARALLEL",
          children: [
            {
              step_type: "SLEEP",
              command_type: null,
              sleep_seconds: 5,
              group_mode: null,
              children: [],
            },
          ],
        },
      ],
    });
    expect(toast.success).toHaveBeenCalledWith("Workflow duplicated");
  });
});
