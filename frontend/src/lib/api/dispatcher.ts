import type { DispatcherStatisticsDTO, DispatcherStatusDTO } from "@/types/api";
import { apiClient } from "./client";

export async function getDispatcherStatus(): Promise<DispatcherStatusDTO> {
  const response = await apiClient.get<DispatcherStatusDTO>("/dispatcher/status");
  return response.data;
}

export async function getDispatcherStatistics(): Promise<DispatcherStatisticsDTO> {
  const response = await apiClient.get<DispatcherStatisticsDTO>("/dispatcher/statistics");
  return response.data;
}
