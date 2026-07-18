import type { SnapshotDTO, SnapshotPageDTO } from "@/types/api";
import { apiClient } from "./client";

export interface ListSnapshotsParams {
  device_id?: string;
  offset?: number;
  limit?: number;
}

export async function listSnapshots(params: ListSnapshotsParams = {}): Promise<SnapshotPageDTO> {
  const response = await apiClient.get<SnapshotPageDTO>("/snapshots", { params });
  return response.data;
}

export async function getSnapshot(id: string): Promise<SnapshotDTO> {
  const response = await apiClient.get<SnapshotDTO>(`/snapshots/${id}`);
  return response.data;
}

export async function deleteSnapshot(id: string): Promise<void> {
  await apiClient.delete(`/snapshots/${id}`);
}
