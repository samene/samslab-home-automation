import { Download, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/shared/ConfirmDialog";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { useDeleteSnapshot, useSnapshot } from "@/hooks/useSnapshots";
import { formatFileSize, formatTimestamp } from "@/lib/format";

interface SnapshotLightboxProps {
  snapshotId: string | null;
  onOpenChange: (open: boolean) => void;
}

export function SnapshotLightbox({ snapshotId, onOpenChange }: SnapshotLightboxProps) {
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const { data: snapshot, isLoading } = useSnapshot(snapshotId ?? undefined);
  const deleteSnapshot = useDeleteSnapshot();

  async function handleConfirmDelete() {
    if (!snapshotId) return;
    await deleteSnapshot.mutateAsync(snapshotId);
    setShowDeleteConfirm(false);
    onOpenChange(false);
  }

  return (
    <>
      <Dialog open={snapshotId !== null} onOpenChange={onOpenChange}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>{snapshot?.filename ?? "Snapshot"}</DialogTitle>
          </DialogHeader>

          {isLoading || !snapshot ? (
            <div className="flex flex-col gap-3">
              <Skeleton className="h-96 w-full rounded-xl" />
              <Skeleton className="h-4 w-1/3" />
            </div>
          ) : (
            <div className="flex flex-col gap-3">
              <div className="flex max-h-[60vh] items-center justify-center overflow-hidden rounded-xl bg-black">
                <img
                  src={snapshot.image_url}
                  alt={snapshot.filename}
                  className="max-h-[60vh] w-full object-contain"
                />
              </div>

              <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
                <div>
                  <dt className="text-xs text-muted-foreground">Captured</dt>
                  <dd className="font-medium">{formatTimestamp(snapshot.captured_at)}</dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground">Resolution</dt>
                  <dd className="font-medium">
                    {snapshot.width}x{snapshot.height}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground">Size</dt>
                  <dd className="font-medium">{formatFileSize(snapshot.size)}</dd>
                </div>
              </dl>

              {snapshot.workflow_name && (
                <p className="text-xs italic text-muted-foreground">
                  Created by workflow{" "}
                  <Link
                    to={`/workflows/${snapshot.workflow_id}/edit`}
                    className="not-italic underline hover:text-foreground"
                  >
                    {snapshot.workflow_name}
                  </Link>
                </p>
              )}

              <div className="flex justify-between gap-2">
                <Button variant="outline" asChild>
                  <a href={snapshot.image_url} download={snapshot.filename} target="_blank" rel="noreferrer">
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
        title="Delete this snapshot?"
        description={
          snapshot ? `Permanently remove "${snapshot.filename}" from storage.` : ""
        }
        confirmLabel="Delete"
        variant="destructive"
        isConfirming={deleteSnapshot.isPending}
        onConfirm={() => void handleConfirmDelete()}
      />
    </>
  );
}
