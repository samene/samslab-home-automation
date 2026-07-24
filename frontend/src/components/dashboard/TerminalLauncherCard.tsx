import { SquareTerminal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

interface TerminalLauncherCardProps {
  disabled: boolean;
  onOpen: () => void;
}

/** Opens the interactive terminal drawer for the primary device — see TerminalDrawer. */
export function TerminalLauncherCard({ disabled, onOpen }: TerminalLauncherCardProps) {
  return (
    <Card className="flex shrink-0 flex-col gap-3 p-4">
      <div className="flex items-center gap-2.5">
        <div className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
          <SquareTerminal className="size-4" />
        </div>
        <div>
          <p className="text-sm font-semibold">Terminal</p>
          <p className="text-xs text-muted-foreground">A live shell on this device</p>
        </div>
      </div>

      <Button
        type="button"
        variant="outline"
        className="w-full rounded-xl"
        disabled={disabled}
        onClick={onOpen}
        data-testid="open-terminal-button"
      >
        <SquareTerminal className="size-4" />
        Terminal
      </Button>
    </Card>
  );
}
