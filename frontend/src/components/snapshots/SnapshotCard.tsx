import { formatFileSize, formatRelativeTime } from "@/lib/format";
import type { SnapshotDTO } from "@/types/api";

interface SnapshotCardProps {
  snapshot: SnapshotDTO;
  deviceName: string;
  onClick: () => void;
}

export function SnapshotCard({ snapshot, deviceName, onClick }: SnapshotCardProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="group flex flex-col overflow-hidden rounded-2xl border border-border bg-card text-left shadow-sm transition-shadow hover:shadow-md"
    >
      <div className="aspect-video w-full overflow-hidden bg-black">
        <img
          loading="lazy"
          src={snapshot.thumbnail_url}
          alt={snapshot.filename}
          className="size-full object-cover transition-transform group-hover:scale-105"
        />
      </div>
      <div className="flex flex-col gap-0.5 p-2.5">
        <p className="truncate text-xs font-medium">{deviceName}</p>
        <p className="truncate text-[11px] text-muted-foreground">
          {formatRelativeTime(snapshot.captured_at)}
        </p>
        <p className="text-[11px] text-muted-foreground">
          {snapshot.width}x{snapshot.height} · {formatFileSize(snapshot.size)}
        </p>
      </div>
    </button>
  );
}
