import { Droplets } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

interface ControlPanelProps {
  onTriggerPump: () => void;
  disabled: boolean;
  triggering: boolean;
}

/**
 * Manual override — always visible, stacked below the device card in column 1.
 *
 * A single "Trigger Pump" action, no stop button: the Pi never controls
 * watering duration, it only pulses a GPIO line to fire a timer relay, which
 * owns the actual run time — see docs/agent/PUMP.md. The button (and badge)
 * shows "Triggering..." only for the brief window the pump.trigger command
 * is in flight, then returns to Idle on its own.
 */
export function ControlPanel({ onTriggerPump, disabled, triggering }: ControlPanelProps) {
  return (
    <Card className="flex shrink-0 flex-col gap-3 p-4">
      <div className="flex items-center gap-2.5">
        <div className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
          <Droplets className="size-4" />
        </div>
        <div>
          <p className="text-sm font-semibold">Pump</p>
          <Badge
            variant={triggering ? "success" : "outline"}
            className="rounded-full text-[11px]"
          >
            {triggering ? "Triggering" : "Idle"}
          </Badge>
        </div>
      </div>

      <Button
        type="button"
        className="w-full rounded-xl"
        disabled={disabled || triggering}
        onClick={onTriggerPump}
      >
        <Droplets className="size-4" />
        {triggering ? "Triggering..." : "Trigger Pump"}
      </Button>
    </Card>
  );
}
