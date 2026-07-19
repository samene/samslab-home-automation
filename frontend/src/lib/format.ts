/** Formatting helpers shared by the dashboard, history, and detail views. */

export function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "medium",
  });
}

export function formatRelativeTime(value: string | null | undefined): string {
  if (!value) return "Never";
  const diffMs = Date.now() - new Date(value).getTime();
  const diffSeconds = Math.round(diffMs / 1000);
  if (diffSeconds < 5) return "just now";
  if (diffSeconds < 60) return `${diffSeconds}s ago`;
  const diffMinutes = Math.round(diffSeconds / 60);
  if (diffMinutes < 60) return `${diffMinutes}m ago`;
  const diffHours = Math.round(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  const diffDays = Math.round(diffHours / 24);
  return `${diffDays}d ago`;
}

/** A countdown to a future timestamp (e.g. "in 3m"), the forward-looking twin of formatRelativeTime. */
export function formatCountdown(value: string | null | undefined): string {
  if (!value) return "—";
  const diffMs = new Date(value).getTime() - Date.now();
  if (diffMs <= 0) return "now";
  const diffSeconds = Math.round(diffMs / 1000);
  if (diffSeconds < 60) return `in ${diffSeconds}s`;
  const diffMinutes = Math.round(diffSeconds / 60);
  if (diffMinutes < 60) return `in ${diffMinutes}m`;
  const diffHours = Math.round(diffMinutes / 60);
  if (diffHours < 24) return `in ${diffHours}h`;
  const diffDays = Math.round(diffHours / 24);
  return `in ${diffDays}d`;
}

export function formatDuration(durationMs: number | null | undefined): string {
  if (durationMs == null) return "—";
  if (durationMs < 1000) return `${durationMs}ms`;
  return `${(durationMs / 1000).toFixed(1)}s`;
}

/** A best-effort thumbnail URL, only present once a real camera command returns one. */
export function getThumbnailUrl(result: Record<string, unknown> | null | undefined): string | null {
  const candidate = result?.thumbnail_url ?? result?.image_url;
  return typeof candidate === "string" ? candidate : null;
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const kilobytes = bytes / 1024;
  if (kilobytes < 1024) return `${Math.round(kilobytes)} KB`;
  return `${(kilobytes / 1024).toFixed(1)} MB`;
}

const COMMAND_LABELS: Record<string, string> = {
  "camera.snapshot": "Snapshot Captured",
};

export function friendlyCommandLabel(commandType: string): string {
  return COMMAND_LABELS[commandType] ?? commandType;
}
