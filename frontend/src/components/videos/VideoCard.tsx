import { Film } from "lucide-react";
import { formatFileSize, formatRelativeTime, formatVideoDuration } from "@/lib/format";
import type { SavedMediaDTO } from "@/types/api";

interface VideoCardProps {
  video: SavedMediaDTO;
  deviceName: string;
  onClick: () => void;
}

export function VideoCard({ video, deviceName, onClick }: VideoCardProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="group flex flex-col overflow-hidden rounded-2xl border border-border bg-card text-left shadow-sm transition-shadow hover:shadow-md"
    >
      <div className="relative flex aspect-video w-full items-center justify-center overflow-hidden bg-muted">
        {video.thumbnail_url ? (
          <img
            loading="lazy"
            src={video.thumbnail_url}
            alt={video.filename}
            className="size-full object-cover transition-transform group-hover:scale-105"
          />
        ) : (
          <Film className="size-8 text-muted-foreground" />
        )}
        {video.duration != null && (
          <span className="absolute right-1.5 bottom-1.5 rounded bg-black/70 px-1.5 py-0.5 text-[10px] font-medium text-white">
            {formatVideoDuration(video.duration)}
          </span>
        )}
      </div>
      <div className="flex flex-col gap-0.5 p-2.5">
        <p className="truncate text-xs font-medium">{deviceName}</p>
        <p className="truncate text-[11px] text-muted-foreground">
          {formatRelativeTime(video.captured_at)}
        </p>
        <p className="text-[11px] text-muted-foreground">
          {video.width}x{video.height} · {formatFileSize(video.size)}
        </p>
        {video.workflow_name && (
          <p className="truncate text-[11px] text-muted-foreground italic">
            Created by workflow &ldquo;{video.workflow_name}&rdquo;
          </p>
        )}
      </div>
    </button>
  );
}
