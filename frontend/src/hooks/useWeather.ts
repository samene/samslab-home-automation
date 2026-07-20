import { useQuery } from "@tanstack/react-query";
import { getWeather } from "@/lib/api/weather";

const FIFTEEN_MINUTES_MS = 15 * 60 * 1000;

/** Weather changes slowly enough that a 15-minute poll is more than fresh enough for a dashboard widget. */
export function useWeather() {
  return useQuery({
    queryKey: ["weather"],
    queryFn: getWeather,
    staleTime: FIFTEEN_MINUTES_MS,
    refetchInterval: FIFTEEN_MINUTES_MS,
    retry: 1,
  });
}
