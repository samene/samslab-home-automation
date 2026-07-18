import { Camera } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useTakeSnapshot } from "@/hooks/useCamera";

interface QuickSnapshotCardProps {
  hasDevice: boolean;
}

/** Standalone quick-capture path — works regardless of whether the live stream is running. */
export function QuickSnapshotCard({ hasDevice }: QuickSnapshotCardProps) {
  const takeSnapshot = useTakeSnapshot();

  return (
    <Card className="flex shrink-0 flex-col gap-3 p-4">
      <div className="flex items-center gap-2.5">
        <div className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-camera/10 text-camera">
          <Camera className="size-4" />
        </div>
        <div>
          <p className="text-sm font-semibold">Quick Snapshot</p>
          <p className="text-xs text-muted-foreground">Capture a photo right now</p>
        </div>
      </div>

      <Button
        type="button"
        className="w-full rounded-xl"
        disabled={!hasDevice || takeSnapshot.isPending}
        onClick={() => takeSnapshot.mutate()}
      >
        <Camera className="size-4" />
        {takeSnapshot.isPending ? "Capturing…" : "Take Snapshot"}
      </Button>
    </Card>
  );
}
