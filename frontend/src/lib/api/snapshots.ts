import type { SavedMediaDTO, SavedMediaPageDTO } from "@/types/api";
import { apiClient } from "./client";

export type SavedMediaRange = "24h" | "3d" | "7d" | "30d" | "90d";

export interface ListSnapshotsParams {
  device_id?: string;
  range?: SavedMediaRange;
  offset?: number;
  limit?: number;
}

/** Function/hook names stay "snapshot"-shaped on purpose — see useSnapshots.ts's
 * module docstring — even though this now calls the generalized Saved Media
 * endpoint scoped to media_type=IMAGE, so SnapshotCard/SnapshotLightbox never change. */
export async function listSnapshots(params: ListSnapshotsParams = {}): Promise<SavedMediaPageDTO> {
  const response = await apiClient.get<SavedMediaPageDTO>("/saved-media", {
    params: { ...params, media_type: "IMAGE" },
  });
  return response.data;
}

export async function getSnapshot(id: string): Promise<SavedMediaDTO> {
  const response = await apiClient.get<SavedMediaDTO>(`/saved-media/${id}`);
  return response.data;
}

export async function deleteSnapshot(id: string): Promise<void> {
  await apiClient.delete(`/saved-media/${id}`);
}
