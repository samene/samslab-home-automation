import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  deleteSnapshot,
  getSnapshot,
  listSnapshots,
  type ListSnapshotsParams,
} from "@/lib/api/snapshots";
import { getErrorMessage } from "@/lib/api/errors";

export function useSnapshots(params: ListSnapshotsParams = {}) {
  return useQuery({
    queryKey: ["snapshots", params],
    queryFn: () => listSnapshots(params),
  });
}

export function useSnapshot(id: string | undefined) {
  return useQuery({
    queryKey: ["snapshots", "detail", id],
    queryFn: () => getSnapshot(id!),
    enabled: Boolean(id),
  });
}

export function useDeleteSnapshot() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deleteSnapshot(id),
    onSuccess: () => {
      toast.success("Snapshot deleted");
      void queryClient.invalidateQueries({ queryKey: ["snapshots"] });
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "Failed to delete snapshot"));
    },
  });
}
