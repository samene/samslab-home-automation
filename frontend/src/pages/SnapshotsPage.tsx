import { useMemo, useState } from "react";
import { SnapshotCard } from "@/components/snapshots/SnapshotCard";
import { SnapshotLightbox } from "@/components/snapshots/SnapshotLightbox";
import { CardGridSkeleton } from "@/components/shared/LoadingSkeleton";
import { Button } from "@/components/ui/button";
import { useDevices } from "@/hooks/useDevices";
import { useSnapshots } from "@/hooks/useSnapshots";

const PAGE_SIZE = 20;

export function SnapshotsPage() {
  const [offset, setOffset] = useState(0);
  const [selectedSnapshotId, setSelectedSnapshotId] = useState<string | null>(null);

  const { data: devicesPage } = useDevices({ limit: 100 });
  const { data: snapshotsPage, isLoading } = useSnapshots({ offset, limit: PAGE_SIZE });

  const deviceNameById = useMemo(() => {
    const map: Record<string, string> = {};
    for (const device of devicesPage?.items ?? []) {
      map[device.id] = device.display_name;
    }
    return map;
  }, [devicesPage]);

  const snapshots = snapshotsPage?.items ?? [];
  const total = snapshotsPage?.total ?? 0;
  const hasNextPage = offset + PAGE_SIZE < total;
  const hasPreviousPage = offset > 0;

  return (
    <div className="h-full overflow-y-auto p-4 sm:p-6 lg:p-8">
      <div className="flex flex-col gap-5">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Snapshots</h1>
          <p className="text-sm text-muted-foreground">Every camera snapshot ever captured, newest first.</p>
        </div>

        {isLoading ? (
          <CardGridSkeleton count={8} />
        ) : snapshots.length === 0 ? (
          <p className="p-8 text-center text-sm text-muted-foreground">No snapshots yet.</p>
        ) : (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
            {snapshots.map((snapshot) => (
              <SnapshotCard
                key={snapshot.id}
                snapshot={snapshot}
                deviceName={deviceNameById[snapshot.device_id] ?? snapshot.device_id}
                onClick={() => setSelectedSnapshotId(snapshot.id)}
              />
            ))}
          </div>
        )}

        <div className="flex items-center justify-between text-sm text-muted-foreground">
          <span>
            {total === 0
              ? "No snapshots"
              : `${offset + 1}–${Math.min(offset + PAGE_SIZE, total)} of ${total}`}
          </span>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              className="rounded-lg"
              disabled={!hasPreviousPage}
              onClick={() => setOffset((current) => Math.max(0, current - PAGE_SIZE))}
            >
              Previous
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="rounded-lg"
              disabled={!hasNextPage}
              onClick={() => setOffset((current) => current + PAGE_SIZE)}
            >
              Next
            </Button>
          </div>
        </div>
      </div>

      <SnapshotLightbox
        snapshotId={selectedSnapshotId}
        onOpenChange={(open) => !open && setSelectedSnapshotId(null)}
      />
    </div>
  );
}
