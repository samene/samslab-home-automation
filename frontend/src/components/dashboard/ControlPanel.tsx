import { Droplet, Droplets } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

interface ControlPanelProps {
  onStartWatering: () => void;
  onStopWatering: () => void;
  disabled: boolean;
  pumpState: "Active" | "Idle" | "Unknown";
}

/** Manual override — always visible, stacked below the device card in column 1. */
export function ControlPanel({
  onStartWatering,
  onStopWatering,
  disabled,
  pumpState,
}: ControlPanelProps) {
  return (
    <Card className="flex shrink-0 flex-col gap-3 p-4">
      <div className="flex items-center gap-2.5">
        <div className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-water/10 text-water">
          <Droplets className="size-4" />
        </div>
        <div>
          <p className="text-sm font-semibold">Pump</p>
          <Badge
            variant={pumpState === "Active" ? "success" : "outline"}
            className="rounded-full text-[11px]"
          >
            {pumpState === "Active" ? "Running" : pumpState === "Idle" ? "Stopped" : "Unknown"}
          </Badge>
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <Button
          type="button"
          className="w-full rounded-xl bg-water text-water-foreground hover:bg-water/90"
          disabled={disabled}
          onClick={onStartWatering}
        >
          <Droplets className="size-4" />
          Start Pump
        </Button>
        <Button
          type="button"
          variant="outline"
          className="w-full rounded-xl"
          disabled={disabled}
          onClick={onStopWatering}
        >
          <Droplet className="size-4" />
          Stop Pump
        </Button>
      </div>
    </Card>
  );
}
