import { useMemo, useState } from "react";
import { CameraPanel } from "@/components/dashboard/CameraPanel";
import { ControlPanel } from "@/components/dashboard/ControlPanel";
import { DeviceHeroCard } from "@/components/dashboard/DeviceHeroCard";
import { QuickSnapshotCard } from "@/components/dashboard/QuickSnapshotCard";
import { RecentActivity } from "@/components/dashboard/RecentActivity";
import { RecentSnapshots } from "@/components/dashboard/RecentSnapshots";
import { SystemStatusPanel } from "@/components/dashboard/SystemStatusPanel";
import { ConfirmDialog } from "@/components/shared/ConfirmDialog";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useStartCameraStream, useStopCameraStream, useTakeSnapshot } from "@/hooks/useCamera";
import { useCreateCommand, useCommands } from "@/hooks/useCommands";
import { usePrimaryDevice } from "@/hooks/useDevices";
import type { CameraStatusDTO } from "@/types/api";

const PUMP_START = "pump.start";
const PUMP_STOP = "pump.stop";

export function DashboardPage() {
  const { data: device, isLoading: isDeviceLoading } = usePrimaryDevice();
  const { data: commandsPage, isLoading: isCommandsLoading } = useCommands({ limit: 10 });
  const createCommand = useCreateCommand();
  const startCameraStream = useStartCameraStream();
  const stopCameraStream = useStopCameraStream();
  const takeSnapshot = useTakeSnapshot();

  const [pendingCommandType, setPendingCommandType] = useState<string | null>(null);
  const [cameraStatus, setCameraStatus] = useState<CameraStatusDTO | null>(null);

  const deviceNameById = useMemo(
    () => (device ? { [device.id]: device.display_name } : {}),
    [device],
  );

  const commands = commandsPage?.items ?? [];
  const latestCommand = commands[0];
  const latestPumpCommand = commands.find((command) => command.command_type.startsWith("pump."));
  const pumpState =
    !latestPumpCommand
      ? "Unknown"
      : latestPumpCommand.command_type === PUMP_START &&
          (latestPumpCommand.status === "DISPATCHED" || latestPumpCommand.status === "RUNNING")
        ? "Active"
        : "Idle";

  async function handleGoLive() {
    const status = await startCameraStream.mutateAsync();
    setCameraStatus(status);
  }

  async function handleStop() {
    await stopCameraStream.mutateAsync();
    setCameraStatus(null);
  }

  async function handleConfirmPumpCommand() {
    if (!pendingCommandType || !device) return;
    await createCommand.mutateAsync({ device_id: device.id, command_type: pendingCommandType });
    setPendingCommandType(null);
  }

  return (
    <div className="flex h-full flex-col gap-3 overflow-hidden p-4 sm:p-6 lg:p-8">
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 overflow-hidden lg:grid-cols-4">
        <div className="flex min-h-0 flex-col gap-3 lg:col-start-1">
          {isDeviceLoading ? (
            <Skeleton className="h-20 w-full shrink-0 rounded-2xl" />
          ) : (
            <DeviceHeroCard device={device} />
          )}
          <ControlPanel
            disabled={!device}
            pumpState={pumpState}
            onStartWatering={() => setPendingCommandType(PUMP_START)}
            onStopWatering={() => setPendingCommandType(PUMP_STOP)}
          />
          <QuickSnapshotCard hasDevice={Boolean(device)} />
        </div>

        <div className="min-h-64 lg:col-span-2 lg:col-start-2 lg:min-h-0">
          <CameraPanel
            hasDevice={Boolean(device)}
            cameraStatus={cameraStatus}
            isStarting={startCameraStream.isPending}
            isStopping={stopCameraStream.isPending}
            onGoLive={() => void handleGoLive()}
            onStop={() => void handleStop()}
            onTakeSnapshot={() => takeSnapshot.mutate()}
            isTakingSnapshot={takeSnapshot.isPending}
          />
        </div>

        <div className="flex min-h-0 flex-col gap-3 lg:col-start-4">
          <Card className="min-h-0 flex-1 overflow-y-auto p-3">
            <h3 className="mb-1 px-1 text-xs font-semibold">Recent Commands</h3>
            {isCommandsLoading ? (
              <div className="flex flex-col gap-2 p-2">
                <Skeleton className="h-10 w-full" />
                <Skeleton className="h-10 w-full" />
                <Skeleton className="h-10 w-full" />
              </div>
            ) : (
              <RecentActivity commands={commands} deviceNameById={deviceNameById} />
            )}
          </Card>
          <RecentSnapshots />
          <SystemStatusPanel device={device} latestCommand={latestCommand} />
        </div>
      </div>

      <ConfirmDialog
        open={pendingCommandType !== null}
        onOpenChange={(open) => !open && setPendingCommandType(null)}
        title={pendingCommandType === PUMP_START ? "Start Watering" : "Stop Watering"}
        description={
          device
            ? `Send "${pendingCommandType}" to ${device.display_name}?`
            : "No device available."
        }
        confirmLabel="Send"
        isConfirming={createCommand.isPending}
        onConfirm={() => void handleConfirmPumpCommand()}
      />
    </div>
  );
}
