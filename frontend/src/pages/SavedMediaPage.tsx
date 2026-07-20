import { useMemo, useState } from "react";
import { SnapshotCard } from "@/components/snapshots/SnapshotCard";
import { SnapshotLightbox } from "@/components/snapshots/SnapshotLightbox";
import { VideoCard } from "@/components/videos/VideoCard";
import { VideoLightbox } from "@/components/videos/VideoLightbox";
import { CardGridSkeleton } from "@/components/shared/LoadingSkeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useDevices } from "@/hooks/useDevices";
import { useSnapshots } from "@/hooks/useSnapshots";
import { useVideos } from "@/hooks/useVideos";
import { groupByDay } from "@/lib/format";
import type { SavedMediaRange } from "@/lib/api/snapshots";
import type { SavedMediaDTO } from "@/types/api";

// Matches PaginationParams' server-side cap (server/app/application/validators/pagination.py) —
// a limit above 100 makes every /saved-media fetch fail with a 422, which this page's
// data ?? [] fallback then silently rendered as "no images/videos yet" instead of an error.
const MEDIA_LIMIT = 100;

const RANGE_OPTIONS: { value: SavedMediaRange | ""; label: string }[] = [
  { value: "24h", label: "Last 24 hours" },
  { value: "3d", label: "Last 3 days" },
  { value: "7d", label: "Last 7 days" },
  { value: "30d", label: "Last 30 days" },
  { value: "90d", label: "Last 90 days" },
  { value: "", label: "All Time" },
];

export function SavedMediaPage() {
  const [range, setRange] = useState<SavedMediaRange | "">("");
  const [selectedSnapshotId, setSelectedSnapshotId] = useState<string | null>(null);
  const [selectedVideoId, setSelectedVideoId] = useState<string | null>(null);

  const rangeParam = range === "" ? undefined : range;
  const { data: devicesPage } = useDevices({ limit: 100 });
  const {
    data: snapshotsPage,
    isLoading: isLoadingImages,
    isError: isImagesError,
  } = useSnapshots({ range: rangeParam, limit: MEDIA_LIMIT });
  const {
    data: videosPage,
    isLoading: isLoadingVideos,
    isError: isVideosError,
  } = useVideos({ range: rangeParam, limit: MEDIA_LIMIT });

  const deviceNameById = useMemo(() => {
    const map: Record<string, string> = {};
    for (const device of devicesPage?.items ?? []) {
      map[device.id] = device.display_name;
    }
    return map;
  }, [devicesPage]);

  const images = snapshotsPage?.items ?? [];
  const videos = videosPage?.items ?? [];
  const imageGroups = groupByDay(images, (item: SavedMediaDTO) => item.captured_at);
  const videoGroups = groupByDay(videos, (item: SavedMediaDTO) => item.captured_at);

  return (
    <div className="h-full overflow-y-auto p-4 sm:p-6 lg:p-8">
      <div className="flex flex-col gap-5">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Saved Media</h1>
            <p className="text-sm text-muted-foreground">
              Every camera snapshot and recording ever captured, newest first.
            </p>
          </div>

          <select
            value={range}
            onChange={(event) => setRange(event.target.value as SavedMediaRange | "")}
            className="h-10 rounded-xl border border-input bg-transparent px-3 text-sm shadow-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring coarse:h-11"
          >
            {RANGE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>

        <Tabs defaultValue="images">
          <TabsList>
            <TabsTrigger value="images">Images</TabsTrigger>
            <TabsTrigger value="videos">Videos</TabsTrigger>
          </TabsList>

          <TabsContent value="images" className="mt-5">
            {isLoadingImages ? (
              <CardGridSkeleton count={8} />
            ) : isImagesError ? (
              <p className="p-8 text-center text-sm text-destructive">Failed to load images.</p>
            ) : images.length === 0 ? (
              <p className="p-8 text-center text-sm text-muted-foreground">No images yet.</p>
            ) : (
              <div className="flex flex-col gap-6">
                {imageGroups.map((group) => (
                  <section key={group.label} className="flex flex-col gap-3">
                    <h2 className="text-sm font-semibold text-muted-foreground">{group.label}</h2>
                    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 2xl:grid-cols-6">
                      {group.items.map((snapshot) => (
                        <SnapshotCard
                          key={snapshot.id}
                          snapshot={snapshot}
                          deviceName={deviceNameById[snapshot.device_id] ?? snapshot.device_id}
                          onClick={() => setSelectedSnapshotId(snapshot.id)}
                        />
                      ))}
                    </div>
                  </section>
                ))}
              </div>
            )}
          </TabsContent>

          <TabsContent value="videos" className="mt-5">
            {isLoadingVideos ? (
              <CardGridSkeleton count={8} />
            ) : isVideosError ? (
              <p className="p-8 text-center text-sm text-destructive">Failed to load videos.</p>
            ) : videos.length === 0 ? (
              <p className="p-8 text-center text-sm text-muted-foreground">No videos yet.</p>
            ) : (
              <div className="flex flex-col gap-6">
                {videoGroups.map((group) => (
                  <section key={group.label} className="flex flex-col gap-3">
                    <h2 className="text-sm font-semibold text-muted-foreground">{group.label}</h2>
                    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 2xl:grid-cols-6">
                      {group.items.map((video) => (
                        <VideoCard
                          key={video.id}
                          video={video}
                          deviceName={deviceNameById[video.device_id] ?? video.device_id}
                          onClick={() => setSelectedVideoId(video.id)}
                        />
                      ))}
                    </div>
                  </section>
                ))}
              </div>
            )}
          </TabsContent>
        </Tabs>
      </div>

      <SnapshotLightbox
        snapshotId={selectedSnapshotId}
        onOpenChange={(open) => !open && setSelectedSnapshotId(null)}
      />
      <VideoLightbox
        videoId={selectedVideoId}
        onOpenChange={(open) => !open && setSelectedVideoId(null)}
      />
    </div>
  );
}
