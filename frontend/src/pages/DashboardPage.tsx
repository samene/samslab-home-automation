import { useMemo, useState } from "react";
import { CameraPanel } from "@/components/dashboard/CameraPanel";
import { ControlPanel } from "@/components/dashboard/ControlPanel";
import { DeviceHeroCard } from "@/components/dashboard/DeviceHeroCard";
import { QuickSnapshotCard } from "@/components/dashboard/QuickSnapshotCard";
import { RecentActivity } from "@/components/dashboard/RecentActivity";
import { RecentWorkflows } from "@/components/dashboard/RecentWorkflows";
import { UpcomingSchedules } from "@/components/dashboard/UpcomingSchedules";
import { WeatherWidget } from "@/components/dashboard/WeatherWidget";
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
    <div className="flex h-full flex-col gap-3 overflow-y-auto p-4 sm:p-6 lg:overflow-hidden lg:p-8">
      {/*
        Mobile/tablet: a normal scrolling single (then two-) column page —
        the dashboard's fixed-viewport, no-page-scroll "mission control"
        density is a desktop-only affordance; forcing it below `lg` would
        clip content with no way to reach it. Camera is always first in
        source order (and `order-1` below `lg`) so it's the first thing
        rendered regardless of viewport — "always the primary focus" — then
        reflows to its original col-2/3 desktop position via `lg:col-start-2`
        once there's room for the full 4-column layout.
      */}
      <div className="grid flex-1 grid-cols-1 gap-3 md:grid-cols-2 lg:min-h-0 lg:grid-cols-4 lg:overflow-hidden">
        <div className="order-1 min-h-[55vh] sm:min-h-[60vh] md:order-1 md:col-span-2 md:min-h-[26rem] lg:order-none lg:col-span-2 lg:col-start-2 lg:row-start-1 lg:min-h-0">
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

        <div className="order-2 flex min-h-0 flex-col gap-3 md:order-2 lg:order-none lg:col-start-1 lg:row-start-1">
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

        <div className="order-3 flex min-h-0 flex-col gap-3 md:order-3 lg:order-none lg:col-start-4 lg:row-start-1">
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
          <WeatherWidget />
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
