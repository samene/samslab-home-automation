import type { DeviceDTO, DevicePageDTO } from "@/types/api";
import { apiClient } from "./client";

export interface ListDevicesParams {
  offset?: number;
  limit?: number;
}

export async function listDevices(params: ListDevicesParams = {}): Promise<DevicePageDTO> {
  const response = await apiClient.get<DevicePageDTO>("/devices", { params });
  return response.data;
}

export async function getDevice(deviceId: string): Promise<DeviceDTO> {
  const response = await apiClient.get<DeviceDTO>(`/devices/${deviceId}`);
  return response.data;
}
