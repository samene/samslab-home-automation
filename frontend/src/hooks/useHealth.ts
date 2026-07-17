import { useQuery } from "@tanstack/react-query";
import { getServiceInfo } from "@/lib/api/health";

export function useServiceInfo() {
  return useQuery({
    queryKey: ["service-info"],
    queryFn: getServiceInfo,
  });
}
