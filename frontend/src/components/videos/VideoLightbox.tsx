import { Download, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/shared/ConfirmDialog";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { useDeleteVideo, useVideo } from "@/hooks/useVideos";
import { formatFileSize, formatTimestamp, formatVideoDuration } from "@/lib/format";

interface VideoLightboxProps {
  videoId: string | null;
  onOpenChange: (open: boolean) => void;
}

export function VideoLightbox({ videoId, onOpenChange }: VideoLightboxProps) {
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const { data: video, isLoading } = useVideo(videoId ?? undefined);
  const deleteVideo = useDeleteVideo();

  async function handleConfirmDelete() {
    if (!videoId) return;
    await deleteVideo.mutateAsync(videoId);
    setShowDeleteConfirm(false);
    onOpenChange(false);
  }

  return (
    <>
      <Dialog open={videoId !== null} onOpenChange={onOpenChange}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>{video?.filename ?? "Video"}</DialogTitle>
          </DialogHeader>

          {isLoading || !video ? (
            <div className="flex flex-col gap-3">
              <Skeleton className="h-96 w-full rounded-xl" />
              <Skeleton className="h-4 w-1/3" />
            </div>
          ) : (
            <div className="flex flex-col gap-3">
              <div className="flex max-h-[60vh] items-center justify-center overflow-hidden rounded-xl bg-black">
                {/* Plays directly from the presigned S3 URL — the browser's
                    native <video> element handles HTTP range-request
                    streaming with zero custom player code. */}
                <video
                  controls
                  src={video.video_url}
                  poster={video.thumbnail_url || undefined}
                  className="max-h-[60vh] w-full"
                >
                  <track kind="captions" />
                </video>
              </div>

              <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
                <div>
                  <dt className="text-xs text-muted-foreground">Captured</dt>
                  <dd className="font-medium">{formatTimestamp(video.captured_at)}</dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground">Duration</dt>
                  <dd className="font-medium">{formatVideoDuration(video.duration)}</dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground">Resolution</dt>
                  <dd className="font-medium">
                    {video.width}x{video.height}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground">Size</dt>
                  <dd className="font-medium">{formatFileSize(video.size)}</dd>
                </div>
              </dl>

              {video.workflow_name && (
                <p className="text-xs italic text-muted-foreground">
                  Created by workflow{" "}
                  <Link
                    to={`/workflows/${video.workflow_id}/edit`}
                    className="not-italic underline hover:text-foreground"
                  >
                    {video.workflow_name}
                  </Link>
                </p>
              )}

              <div className="flex justify-between gap-2">
                <Button variant="outline" asChild>
                  <a href={video.video_url} download={video.filename} target="_blank" rel="noreferrer">
                    <Download className="size-4" />
                    Download
                  </a>
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  className="text-destructive hover:bg-destructive/10 hover:text-destructive"
                  onClick={() => setShowDeleteConfirm(true)}
                >
                  <Trash2 className="size-4" />
                  Delete
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={showDeleteConfirm}
        onOpenChange={setShowDeleteConfirm}
        title="Delete this video?"
        description={video ? `Permanently remove "${video.filename}" from storage.` : ""}
        confirmLabel="Delete"
        variant="destructive"
        isConfirming={deleteVideo.isPending}
        onConfirm={() => void handleConfirmDelete()}
      />
    </>
  );
}
