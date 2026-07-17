import { useQuery } from "@tanstack/react-query";
import { getDispatcherStatistics, getDispatcherStatus } from "@/lib/api/dispatcher";

/** Live updates come from polling, not a browser WebSocket — see README "Live updates". */
const LIVE_REFETCH_INTERVAL_MS = 3000;

/** Requires `system.admin`; a Viewer-role session simply won't see this panel populate. */
export function useDispatcherStatus() {
  return useQuery({
    queryKey: ["dispatcher", "status"],
    queryFn: getDispatcherStatus,
    refetchInterval: LIVE_REFETCH_INTERVAL_MS,
    retry: false,
  });
}

export function useDispatcherStatistics() {
  return useQuery({
    queryKey: ["dispatcher", "statistics"],
    queryFn: getDispatcherStatistics,
    refetchInterval: LIVE_REFETCH_INTERVAL_MS,
    retry: false,
  });
}
