import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { getErrorMessage } from "@/lib/api/errors";
import { getNotificationStatus, sendTestNotification } from "@/lib/api/notifications";

const NOTIFICATION_STATUS_QUERY_KEY = ["notifications", "status"];

export function useNotificationStatus() {
  return useQuery({
    queryKey: NOTIFICATION_STATUS_QUERY_KEY,
    queryFn: getNotificationStatus,
  });
}

/**
 * A 200 response here can still mean "delivery failed" per-provider — that's
 * data for the caller to render, not a thrown error. `onError` only fires
 * for a genuine request failure (network/server error), not a failed send.
 */
export function useSendTestNotification() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: sendTestNotification,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: NOTIFICATION_STATUS_QUERY_KEY });
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "Failed to send test notification"));
    },
  });
}
