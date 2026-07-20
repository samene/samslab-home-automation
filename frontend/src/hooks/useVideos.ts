import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { deleteVideo, getVideo, listVideos, type ListVideosParams } from "@/lib/api/videos";
import { getErrorMessage } from "@/lib/api/errors";

export function useVideos(params: ListVideosParams = {}) {
  return useQuery({
    queryKey: ["videos", params],
    queryFn: () => listVideos(params),
  });
}

export function useVideo(id: string | undefined) {
  return useQuery({
    queryKey: ["videos", "detail", id],
    queryFn: () => getVideo(id!),
    enabled: Boolean(id),
  });
}

export function useDeleteVideo() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deleteVideo(id),
    onSuccess: () => {
      toast.success("Video deleted");
      void queryClient.invalidateQueries({ queryKey: ["videos"] });
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "Failed to delete video"));
    },
  });
}
