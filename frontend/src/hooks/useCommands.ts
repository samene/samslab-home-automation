import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  cancelCommand,
  createCommand,
  deleteCommand,
  getCommand,
  listCommands,
  type ListCommandsParams,
} from "@/lib/api/commands";
import { getErrorMessage } from "@/lib/api/errors";
import type { CommandCreateRequest } from "@/types/api";

const LIVE_REFETCH_INTERVAL_MS = 5000;

export function useCommands(params: ListCommandsParams = {}) {
  return useQuery({
    queryKey: ["commands", params],
    queryFn: () => listCommands(params),
    refetchInterval: LIVE_REFETCH_INTERVAL_MS,
  });
}

export function useCommand(commandId: string | undefined) {
  return useQuery({
    queryKey: ["commands", "detail", commandId],
    queryFn: () => getCommand(commandId!),
    enabled: Boolean(commandId),
    refetchInterval: LIVE_REFETCH_INTERVAL_MS,
  });
}

export function useCreateCommand() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: CommandCreateRequest) => createCommand(request),
    onSuccess: (command) => {
      toast.success(`${command.command_type} sent`);
      void queryClient.invalidateQueries({ queryKey: ["commands"] });
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "Failed to send command"));
    },
  });
}

export function useCancelCommand() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ commandId, reason }: { commandId: string; reason?: string }) =>
      cancelCommand(commandId, reason),
    onSuccess: () => {
      toast.success("Command cancelled");
      void queryClient.invalidateQueries({ queryKey: ["commands"] });
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "Failed to cancel command"));
    },
  });
}

export function useDeleteCommand() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (commandId: string) => deleteCommand(commandId),
    onSuccess: () => {
      toast.success("Command deleted");
      void queryClient.invalidateQueries({ queryKey: ["commands"] });
    },
    onError: (error) => {
      toast.error(
        getErrorMessage(error, "Failed to delete command — only finished commands can be deleted"),
      );
    },
  });
}

export function useBulkDeleteCommands() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (commandIds: string[]) => {
      const results = await Promise.allSettled(commandIds.map((id) => deleteCommand(id)));
      const failed = results.filter((result) => result.status === "rejected").length;
      return { total: commandIds.length, failed };
    },
    onSuccess: ({ total, failed }) => {
      const succeeded = total - failed;
      if (failed === 0) {
        toast.success(`${succeeded} command${succeeded === 1 ? "" : "s"} deleted`);
      } else {
        toast.error(
          `${succeeded} of ${total} commands deleted — ${failed} could not be deleted (only finished commands can be deleted)`,
        );
      }
      void queryClient.invalidateQueries({ queryKey: ["commands"] });
    },
  });
}
