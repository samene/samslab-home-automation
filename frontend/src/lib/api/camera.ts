import type { CameraSnapshotDTO, CameraStatusDTO, CameraStopDTO } from "@/types/api";
import { apiClient } from "./client";

export async function startCameraStream(): Promise<CameraStatusDTO> {
  const response = await apiClient.post<CameraStatusDTO>("/camera/start");
  return response.data;
}

export async function takeSnapshot(): Promise<CameraSnapshotDTO> {
  const response = await apiClient.post<CameraSnapshotDTO>("/camera/snapshot");
  return response.data;
}

export async function stopCameraStream(): Promise<CameraStopDTO> {
  const response = await apiClient.post<CameraStopDTO>("/camera/stop");
  return response.data;
}

export async function getCameraStatus(): Promise<CameraStatusDTO> {
  const response = await apiClient.get<CameraStatusDTO>("/camera/status");
  return response.data;
}
