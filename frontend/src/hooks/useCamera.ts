import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { getCameraStatus, startCameraStream, stopCameraStream } from "@/lib/api/camera";
import { getErrorMessage } from "@/lib/api/errors";

const CAMERA_STATUS_QUERY_KEY = ["camera", "status"];

/** Live updates come from polling, not a browser WebSocket — see README "Live updates". */
const LIVE_REFETCH_INTERVAL_MS = 5000;

export function useCameraStatus(options: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: CAMERA_STATUS_QUERY_KEY,
    queryFn: getCameraStatus,
    enabled: options.enabled ?? true,
    refetchInterval: LIVE_REFETCH_INTERVAL_MS,
  });
}

export function useStartCameraStream() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: startCameraStream,
    onSuccess: (status) => {
      queryClient.setQueryData(CAMERA_STATUS_QUERY_KEY, status);
      toast.success("Camera stream started");
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "Failed to start camera stream"));
    },
  });
}

export function useStopCameraStream() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: stopCameraStream,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: CAMERA_STATUS_QUERY_KEY });
      toast.success("Camera stream stopped");
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "Failed to stop camera stream"));
    },
  });
}
