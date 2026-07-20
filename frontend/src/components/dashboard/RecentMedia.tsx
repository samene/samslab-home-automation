import { useMemo, useState } from "react";
import { SnapshotLightbox } from "@/components/snapshots/SnapshotLightbox";
import { VideoLightbox } from "@/components/videos/VideoLightbox";
import { Card } from "@/components/ui/card";
import { useSnapshots } from "@/hooks/useSnapshots";
import { useVideos } from "@/hooks/useVideos";
import type { SavedMediaDTO } from "@/types/api";

const RECENT_MEDIA_LIMIT = 3;

/** Self-contained, mirroring how CameraPanel fetches its own status internally. */
export function RecentMedia() {
  const { data: snapshotsPage } = useSnapshots({ limit: RECENT_MEDIA_LIMIT });
  const { data: videosPage } = useVideos({ limit: RECENT_MEDIA_LIMIT });
  const [selectedSnapshotId, setSelectedSnapshotId] = useState<string | null>(null);
  const [selectedVideoId, setSelectedVideoId] = useState<string | null>(null);

  const recentMedia = useMemo(() => {
    const combined: SavedMediaDTO[] = [
      ...(snapshotsPage?.items ?? []),
      ...(videosPage?.items ?? []),
    ];
    return combined
      .sort((a, b) => new Date(b.captured_at).getTime() - new Date(a.captured_at).getTime())
      .slice(0, RECENT_MEDIA_LIMIT);
  }, [snapshotsPage, videosPage]);

  return (
    <Card className="flex shrink-0 flex-col gap-2 p-3">
      <h3 className="px-1 text-xs font-semibold">Recent Media</h3>
      {recentMedia.length === 0 ? (
        <p className="px-1 py-2 text-center text-xs text-muted-foreground">No media yet.</p>
      ) : (
        <div className="flex gap-2">
          {recentMedia.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() =>
                item.media_type === "VIDEO"
                  ? setSelectedVideoId(item.id)
                  : setSelectedSnapshotId(item.id)
              }
              className="relative flex size-14 shrink-0 items-center justify-center overflow-hidden rounded-lg border border-border bg-muted"
            >
              {item.thumbnail_url ? (
                <>
                  <span className="sr-only">{item.media_type === "VIDEO" ? "Video" : "Image"}</span>
                  <img
                    loading="lazy"
                    src={item.thumbnail_url}
                    alt={item.filename}
                    className="size-full object-cover"
                  />
                  <span className="absolute right-0.5 bottom-0.5 text-[10px]" aria-hidden>
                    {item.media_type === "VIDEO" ? "🎥" : "📷"}
                  </span>
                </>
              ) : (
                <span className="text-lg" aria-hidden>
                  {item.media_type === "VIDEO" ? "🎥" : "📷"}
                </span>
              )}
            </button>
          ))}
        </div>
      )}

      <SnapshotLightbox
        snapshotId={selectedSnapshotId}
        onOpenChange={(open) => !open && setSelectedSnapshotId(null)}
      />
      <VideoLightbox
        videoId={selectedVideoId}
        onOpenChange={(open) => !open && setSelectedVideoId(null)}
      />
    </Card>
  );
}
