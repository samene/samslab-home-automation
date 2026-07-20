import type { SavedMediaDTO, SavedMediaPageDTO } from "@/types/api";
import { apiClient } from "./client";
import type { ListSnapshotsParams } from "./snapshots";

export type ListVideosParams = ListSnapshotsParams;

export async function listVideos(params: ListVideosParams = {}): Promise<SavedMediaPageDTO> {
  const response = await apiClient.get<SavedMediaPageDTO>("/saved-media", {
    params: { ...params, media_type: "VIDEO" },
  });
  return response.data;
}

export async function getVideo(id: string): Promise<SavedMediaDTO> {
  const response = await apiClient.get<SavedMediaDTO>(`/saved-media/${id}`);
  return response.data;
}

export async function deleteVideo(id: string): Promise<void> {
  await apiClient.delete(`/saved-media/${id}`);
}
