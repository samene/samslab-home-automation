import { useState } from "react";
import { SnapshotLightbox } from "@/components/snapshots/SnapshotLightbox";
import { Card } from "@/components/ui/card";
import { useSnapshots } from "@/hooks/useSnapshots";

/** Self-contained, mirroring how CameraPanel fetches its own status internally. */
export function RecentSnapshots() {
  const { data: snapshotsPage } = useSnapshots({ limit: 3 });
  const [selectedSnapshotId, setSelectedSnapshotId] = useState<string | null>(null);

  const snapshots = snapshotsPage?.items ?? [];

  return (
    <Card className="flex shrink-0 flex-col gap-2 p-3">
      <h3 className="px-1 text-xs font-semibold">Recent Snapshots</h3>
      {snapshots.length === 0 ? (
        <p className="px-1 py-2 text-center text-xs text-muted-foreground">No snapshots yet.</p>
      ) : (
        <div className="flex gap-2">
          {snapshots.map((snapshot) => (
            <button
              key={snapshot.id}
              type="button"
              onClick={() => setSelectedSnapshotId(snapshot.id)}
              className="size-14 shrink-0 overflow-hidden rounded-lg border border-border"
            >
              <img
                loading="lazy"
                src={snapshot.thumbnail_url}
                alt={snapshot.filename}
                className="size-full object-cover"
              />
            </button>
          ))}
        </div>
      )}

      <SnapshotLightbox
        snapshotId={selectedSnapshotId}
        onOpenChange={(open) => !open && setSelectedSnapshotId(null)}
      />
    </Card>
  );
}
