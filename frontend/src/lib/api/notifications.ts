import type { NotificationStatusDTO, TestNotificationResultDTO } from "@/types/api";
import { apiClient } from "./client";

export async function getNotificationStatus(): Promise<NotificationStatusDTO> {
  const response = await apiClient.get<NotificationStatusDTO>("/notifications/status");
  return response.data;
}

export async function sendTestNotification(): Promise<TestNotificationResultDTO[]> {
  const response = await apiClient.post<TestNotificationResultDTO[]>("/notifications/test");
  return response.data;
}
