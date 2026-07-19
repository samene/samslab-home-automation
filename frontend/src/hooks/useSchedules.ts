import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  createSchedule,
  deleteSchedule,
  disableSchedule,
  enableSchedule,
  getSchedule,
  listScheduleExecutions,
  listSchedules,
  runScheduleNow,
  updateSchedule,
  type ListScheduleExecutionsParams,
  type ListSchedulesParams,
} from "@/lib/api/schedules";
import { getErrorMessage } from "@/lib/api/errors";
import type { ScheduleCreateRequest, ScheduleDTO } from "@/types/api";

const LIVE_RUN_REFETCH_INTERVAL_MS = 2000;

export function useSchedules(params: ListSchedulesParams = {}) {
  return useQuery({
    queryKey: ["schedules", params],
    queryFn: () => listSchedules(params),
  });
}

/** Poll every 2s only while the schedule's last firing is still RUNNING — mirrors useWorkflow's own getWorkflowRefetchInterval. */
export function getScheduleRefetchInterval(data: ScheduleDTO | undefined): number | false {
  return data?.last_status === "RUNNING" ? LIVE_RUN_REFETCH_INTERVAL_MS : false;
}

export function useSchedule(id: string | undefined) {
  return useQuery({
    queryKey: ["schedules", "detail", id],
    queryFn: () => getSchedule(id!),
    enabled: Boolean(id),
    refetchInterval: (query) => getScheduleRefetchInterval(query.state.data),
  });
}

export function useCreateSchedule() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: ScheduleCreateRequest) => createSchedule(request),
    onSuccess: () => {
      toast.success("Schedule created");
      void queryClient.invalidateQueries({ queryKey: ["schedules"] });
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "Failed to create schedule"));
    },
  });
}

export function useUpdateSchedule() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, request }: { id: string; request: ScheduleCreateRequest }) =>
      updateSchedule(id, request),
    onSuccess: () => {
      toast.success("Schedule updated");
      void queryClient.invalidateQueries({ queryKey: ["schedules"] });
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "Failed to update schedule"));
    },
  });
}

export function useDeleteSchedule() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, deleteArtifacts }: { id: string; deleteArtifacts?: boolean }) =>
      deleteSchedule(id, { deleteArtifacts }),
    onSuccess: () => {
      toast.success("Schedule deleted");
      void queryClient.invalidateQueries({ queryKey: ["schedules"] });
      void queryClient.invalidateQueries({ queryKey: ["snapshots"] });
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "Failed to delete schedule"));
    },
  });
}

export function useRunScheduleNow() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => runScheduleNow(id),
    onSuccess: () => {
      toast.success("Workflow started");
      void queryClient.invalidateQueries({ queryKey: ["schedules"] });
      void queryClient.invalidateQueries({ queryKey: ["workflows"] });
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "Failed to start workflow"));
    },
  });
}

export function useEnableSchedule() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => enableSchedule(id),
    onSuccess: () => {
      toast.success("Schedule enabled");
      void queryClient.invalidateQueries({ queryKey: ["schedules"] });
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "Failed to enable schedule"));
    },
  });
}

export function useDisableSchedule() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => disableSchedule(id),
    onSuccess: () => {
      toast.success("Schedule disabled");
      void queryClient.invalidateQueries({ queryKey: ["schedules"] });
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "Failed to disable schedule"));
    },
  });
}

export function useScheduleExecutions(params: ListScheduleExecutionsParams = {}) {
  return useQuery({
    queryKey: ["schedules", "executions", params],
    queryFn: () => listScheduleExecutions(params),
  });
}
