import { useMemo, useState } from "react";
import { CameraPanel } from "@/components/dashboard/CameraPanel";
import { ControlPanel } from "@/components/dashboard/ControlPanel";
import { DeviceHeroCard } from "@/components/dashboard/DeviceHeroCard";
import { QuickSnapshotCard } from "@/components/dashboard/QuickSnapshotCard";
import { RecentActivity } from "@/components/dashboard/RecentActivity";
import { RecentMedia } from "@/components/dashboard/RecentMedia";
import { RecentWorkflows } from "@/components/dashboard/RecentWorkflows";
import { SystemStatusPanel } from "@/components/dashboard/SystemStatusPanel";
import { UpcomingSchedules } from "@/components/dashboard/UpcomingSchedules";
import { ConfirmDialog } from "@/components/shared/ConfirmDialog";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useStartCameraStream, useStopCameraStream, useTakeSnapshot } from "@/hooks/useCamera";
import { useCreateCommand, useCommands } from "@/hooks/useCommands";
import { usePrimaryDevice } from "@/hooks/useDevices";
import type { CameraStatusDTO } from "@/types/api";

const PUMP_TRIGGER = "pump.trigger";

export function DashboardPage() {
  const { data: device, isLoading: isDeviceLoading } = usePrimaryDevice();
  const { data: commandsPage, isLoading: isCommandsLoading } = useCommands({ limit: 10 });
  const createCommand = useCreateCommand();
  const startCameraStream = useStartCameraStream();
  const stopCameraStream = useStopCameraStream();
  const takeSnapshot = useTakeSnapshot();

  const [pumpConfirmOpen, setPumpConfirmOpen] = useState(false);
  const [cameraStatus, setCameraStatus] = useState<CameraStatusDTO | null>(null);

  const deviceNameById = useMemo(
    () => (device ? { [device.id]: device.display_name } : {}),
    [device],
  );

  const commands = commandsPage?.items ?? [];
  const latestCommand = commands[0];
  const latestPumpCommand = commands.find((command) => command.command_type === PUMP_TRIGGER);
  // The pulse itself is brief — "Triggering" only reflects the one in-flight
  // pump.trigger command, then falls back to Idle on its own; there is no
  // "Active"/"Running" pump state, since the Pi never controls watering
  // duration (the timer relay does — see docs/agent/PUMP.md).
  const pumpTriggering =
    latestPumpCommand?.status === "DISPATCHED" || latestPumpCommand?.status === "RUNNING";

  async function handleGoLive() {
    const status = await startCameraStream.mutateAsync();
    setCameraStatus(status);
  }

  async function handleStop() {
    await stopCameraStream.mutateAsync();
    setCameraStatus(null);
  }

  async function handleConfirmPumpTrigger() {
    if (!device) return;
    await createCommand.mutateAsync({ device_id: device.id, command_type: PUMP_TRIGGER });
    setPumpConfirmOpen(false);
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
            triggering={pumpTriggering}
            onTriggerPump={() => setPumpConfirmOpen(true)}
          />
          <QuickSnapshotCard hasDevice={Boolean(device)} />
          <RecentWorkflows />
          <UpcomingSchedules />
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
          <RecentMedia />
          <SystemStatusPanel device={device} latestCommand={latestCommand} />
        </div>
      </div>

      <ConfirmDialog
        open={pumpConfirmOpen}
        onOpenChange={setPumpConfirmOpen}
        title="Trigger Pump"
        description={
          device
            ? `Send "${PUMP_TRIGGER}" to ${device.display_name}? This fires a short GPIO pulse to trigger the timer relay, which controls the actual watering duration.`
            : "No device available."
        }
        confirmLabel="Trigger"
        isConfirming={createCommand.isPending}
        onConfirm={() => void handleConfirmPumpTrigger()}
      />
    </div>
  );
}
