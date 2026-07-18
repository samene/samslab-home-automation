import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  createWorkflow,
  deleteWorkflow,
  getWorkflow,
  listWorkflows,
  runWorkflow,
  updateWorkflow,
  type ListWorkflowsParams,
} from "@/lib/api/workflows";
import { getErrorMessage } from "@/lib/api/errors";
import type { WorkflowCreateRequest, WorkflowDetailDTO } from "@/types/api";

const LIVE_RUN_REFETCH_INTERVAL_MS = 2000;

export function useWorkflows(params: ListWorkflowsParams = {}) {
  return useQuery({
    queryKey: ["workflows", params],
    queryFn: () => listWorkflows(params),
  });
}

/** Poll every 2s only while the latest run is still in flight — otherwise a finished/never-run workflow shouldn't keep hitting the API. Exported standalone so its branching can be asserted directly, without needing to reach into a live query's internals. */
export function getWorkflowRefetchInterval(data: WorkflowDetailDTO | undefined): number | false {
  return data?.latest_run?.status === "RUNNING" ? LIVE_RUN_REFETCH_INTERVAL_MS : false;
}

export function useWorkflow(id: string | undefined) {
  return useQuery({
    queryKey: ["workflows", "detail", id],
    queryFn: () => getWorkflow(id!),
    enabled: Boolean(id),
    refetchInterval: (query) => getWorkflowRefetchInterval(query.state.data),
  });
}

export function useCreateWorkflow() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: WorkflowCreateRequest) => createWorkflow(request),
    onSuccess: () => {
      toast.success("Workflow created");
      void queryClient.invalidateQueries({ queryKey: ["workflows"] });
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "Failed to create workflow"));
    },
  });
}

export function useUpdateWorkflow() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, request }: { id: string; request: WorkflowCreateRequest }) =>
      updateWorkflow(id, request),
    onSuccess: () => {
      toast.success("Workflow updated");
      void queryClient.invalidateQueries({ queryKey: ["workflows"] });
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "Failed to update workflow"));
    },
  });
}

export function useDeleteWorkflow() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, deleteArtifacts }: { id: string; deleteArtifacts?: boolean }) =>
      deleteWorkflow(id, { deleteArtifacts }),
    onSuccess: () => {
      toast.success("Workflow deleted");
      void queryClient.invalidateQueries({ queryKey: ["workflows"] });
      void queryClient.invalidateQueries({ queryKey: ["snapshots"] });
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "Failed to delete workflow"));
    },
  });
}

export function useRunWorkflow() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => runWorkflow(id),
    onSuccess: () => {
      toast.success("Workflow started");
      void queryClient.invalidateQueries({ queryKey: ["workflows"] });
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "Failed to start workflow"));
    },
  });
}

/** Strip server-generated fields recursively so a fetched step tree can be resubmitted as a create request. */
function stripStepIds(
  steps: WorkflowDetailDTO["steps"],
): WorkflowCreateRequest["steps"] {
  return steps.map((step) => ({
    step_type: step.step_type,
    command_type: step.command_type,
    sleep_seconds: step.sleep_seconds,
    group_mode: step.group_mode,
    children: stripStepIds(step.children),
  }));
}

/** Frontend-only "duplicate": fetch the full workflow, then create a new one with the same steps. No new backend route. */
export function useDuplicateWorkflow() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      const workflow = await getWorkflow(id);
      return createWorkflow({
        name: `${workflow.name} (Copy)`,
        description: workflow.description,
        enabled: workflow.enabled,
        steps: stripStepIds(workflow.steps),
      });
    },
    onSuccess: () => {
      toast.success("Workflow duplicated");
      void queryClient.invalidateQueries({ queryKey: ["workflows"] });
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "Failed to duplicate workflow"));
    },
  });
}
