import type {
  ScheduleCreateRequest,
  ScheduleDTO,
  ScheduleExecutionPageDTO,
  SchedulePageDTO,
  WorkflowDetailDTO,
} from "@/types/api";
import { apiClient } from "./client";

export interface ListSchedulesParams {
  offset?: number;
  limit?: number;
  enabled?: boolean;
  workflow_id?: string;
}

export async function listSchedules(params: ListSchedulesParams = {}): Promise<SchedulePageDTO> {
  const response = await apiClient.get<SchedulePageDTO>("/schedules", { params });
  return response.data;
}

export async function getSchedule(id: string): Promise<ScheduleDTO> {
  const response = await apiClient.get<ScheduleDTO>(`/schedules/${id}`);
  return response.data;
}

export async function createSchedule(request: ScheduleCreateRequest): Promise<ScheduleDTO> {
  const response = await apiClient.post<ScheduleDTO>("/schedules", request);
  return response.data;
}

export async function updateSchedule(
  id: string,
  request: ScheduleCreateRequest,
): Promise<ScheduleDTO> {
  const response = await apiClient.put<ScheduleDTO>(`/schedules/${id}`, request);
  return response.data;
}

export async function deleteSchedule(
  id: string,
  { deleteArtifacts }: { deleteArtifacts?: boolean } = {},
): Promise<void> {
  await apiClient.delete(`/schedules/${id}`, {
    params: { delete_artifacts: deleteArtifacts ?? false },
  });
}

export async function runScheduleNow(id: string): Promise<WorkflowDetailDTO> {
  const response = await apiClient.post<WorkflowDetailDTO>(`/schedules/${id}/run`);
  return response.data;
}

export async function enableSchedule(id: string): Promise<ScheduleDTO> {
  const response = await apiClient.post<ScheduleDTO>(`/schedules/${id}/enable`);
  return response.data;
}

export async function disableSchedule(id: string): Promise<ScheduleDTO> {
  const response = await apiClient.post<ScheduleDTO>(`/schedules/${id}/disable`);
  return response.data;
}

export interface ListScheduleExecutionsParams {
  offset?: number;
  limit?: number;
}

export async function listScheduleExecutions(
  params: ListScheduleExecutionsParams = {},
): Promise<ScheduleExecutionPageDTO> {
  const response = await apiClient.get<ScheduleExecutionPageDTO>("/schedules/executions", {
    params,
  });
  return response.data;
}
