import { useQuery } from "@tanstack/react-query";
import { getDevice, listDevices, type ListDevicesParams } from "@/lib/api/devices";

/** Live updates come from polling, not a browser WebSocket — see README "Live updates". */
const LIVE_REFETCH_INTERVAL_MS = 5000;

export function useDevices(params: ListDevicesParams = {}) {
  return useQuery({
    queryKey: ["devices", params],
    queryFn: () => listDevices(params),
    refetchInterval: LIVE_REFETCH_INTERVAL_MS,
  });
}

export function useDevice(deviceId: string | undefined) {
  return useQuery({
    queryKey: ["devices", deviceId],
    queryFn: () => getDevice(deviceId!),
    enabled: Boolean(deviceId),
    refetchInterval: LIVE_REFETCH_INTERVAL_MS,
  });
}

/**
 * This is an MVP for a single Raspberry Pi: the dashboard shows the first
 * registered device. Multi-device support later is a matter of adding a
 * device switcher/list page on top of the same `useDevices()` data — nothing
 * here needs to change.
 */
export function usePrimaryDevice() {
  const devicesQuery = useDevices({ limit: 1 });
  return {
    ...devicesQuery,
    data: devicesQuery.data?.items[0],
  };
}
