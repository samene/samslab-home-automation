import type {
  WorkflowCreateRequest,
  WorkflowDetailDTO,
  WorkflowPageDTO,
  WorkflowRunDTO,
} from "@/types/api";
import { apiClient } from "./client";

export interface ListWorkflowsParams {
  offset?: number;
  limit?: number;
}

export async function listWorkflows(params: ListWorkflowsParams = {}): Promise<WorkflowPageDTO> {
  const response = await apiClient.get<WorkflowPageDTO>("/workflows", { params });
  return response.data;
}

export async function getWorkflow(id: string): Promise<WorkflowDetailDTO> {
  const response = await apiClient.get<WorkflowDetailDTO>(`/workflows/${id}`);
  return response.data;
}

export async function createWorkflow(request: WorkflowCreateRequest): Promise<WorkflowDetailDTO> {
  const response = await apiClient.post<WorkflowDetailDTO>("/workflows", request);
  return response.data;
}

export async function updateWorkflow(
  id: string,
  request: WorkflowCreateRequest,
): Promise<WorkflowDetailDTO> {
  const response = await apiClient.put<WorkflowDetailDTO>(`/workflows/${id}`, request);
  return response.data;
}

export async function deleteWorkflow(
  id: string,
  { deleteArtifacts }: { deleteArtifacts?: boolean } = {},
): Promise<void> {
  await apiClient.delete(`/workflows/${id}`, {
    params: { delete_artifacts: deleteArtifacts ?? false },
  });
}

export async function runWorkflow(id: string): Promise<WorkflowRunDTO> {
  const response = await apiClient.post<WorkflowRunDTO>(`/workflows/${id}/run`);
  return response.data;
}
