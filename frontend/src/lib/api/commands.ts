import type {
  CommandCreateRequest,
  CommandDetailDTO,
  CommandPageDTO,
  CommandStatus,
} from "@/types/api";
import { apiClient } from "./client";

export interface ListCommandsParams {
  status?: CommandStatus;
  device?: string;
  offset?: number;
  limit?: number;
  sort?: string;
}

export async function listCommands(params: ListCommandsParams = {}): Promise<CommandPageDTO> {
  const response = await apiClient.get<CommandPageDTO>("/commands", { params });
  return response.data;
}

export async function getCommand(commandId: string): Promise<CommandDetailDTO> {
  const response = await apiClient.get<CommandDetailDTO>(`/commands/${commandId}`);
  return response.data;
}

export async function createCommand(request: CommandCreateRequest): Promise<CommandDetailDTO> {
  const response = await apiClient.post<CommandDetailDTO>("/commands", request);
  return response.data;
}

export async function cancelCommand(commandId: string, reason?: string): Promise<CommandDetailDTO> {
  const response = await apiClient.post<CommandDetailDTO>(`/commands/${commandId}/cancel`, {
    reason,
  });
  return response.data;
}

export async function deleteCommand(commandId: string): Promise<void> {
  await apiClient.delete(`/commands/${commandId}`);
}
