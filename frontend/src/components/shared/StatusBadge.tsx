import { Badge, type badgeVariants } from "@/components/ui/badge";
import type { VariantProps } from "class-variance-authority";
import type { CommandStatus, DeviceStatus } from "@/types/api";

type BadgeVariant = VariantProps<typeof badgeVariants>["variant"];

const DEVICE_STATUS_VARIANT: Record<DeviceStatus, BadgeVariant> = {
  ONLINE: "success",
  OFFLINE: "outline",
  REGISTERING: "secondary",
  UNHEALTHY: "warning",
  DISCONNECTED: "outline",
  DISABLED: "destructive",
  UNKNOWN: "outline",
};

const COMMAND_STATUS_VARIANT: Record<CommandStatus, BadgeVariant> = {
  PENDING: "secondary",
  QUEUED: "secondary",
  DISPATCHED: "default",
  RUNNING: "default",
  COMPLETED: "success",
  FAILED: "destructive",
  CANCELLED: "outline",
  EXPIRED: "outline",
  TIMEOUT: "warning",
};

function toTitleCase(value: string) {
  return value.charAt(0) + value.slice(1).toLowerCase();
}

export function DeviceStatusBadge({ status, className }: { status: DeviceStatus; className?: string }) {
  return (
    <Badge variant={DEVICE_STATUS_VARIANT[status]} className={className}>
      {toTitleCase(status)}
    </Badge>
  );
}

export function CommandStatusBadge({
  status,
  className,
}: {
  status: CommandStatus;
  className?: string;
}) {
  return (
    <Badge variant={COMMAND_STATUS_VARIANT[status]} className={className}>
      {toTitleCase(status)}
    </Badge>
  );
}
