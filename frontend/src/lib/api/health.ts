import type { ServiceInfoDTO } from "@/types/api";
import { apiClient } from "./client";

export async function getServiceInfo(): Promise<ServiceInfoDTO> {
  const response = await apiClient.get<ServiceInfoDTO>("/");
  return response.data;
}
