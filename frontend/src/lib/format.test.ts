import { describe, expect, it } from "vitest";
import {
  formatDuration,
  formatFileSize,
  formatRelativeTime,
  formatTimestamp,
  friendlyCommandLabel,
  getThumbnailUrl,
} from "./format";

describe("formatTimestamp", () => {
  it("returns an em dash for null/undefined", () => {
    expect(formatTimestamp(null)).toBe("—");
    expect(formatTimestamp(undefined)).toBe("—");
  });

  it("formats an ISO string into a locale date/time string", () => {
    const result = formatTimestamp("2026-01-15T10:30:00Z");
    expect(result).not.toBe("—");
    expect(result.length).toBeGreaterThan(0);
  });
});

describe("formatRelativeTime", () => {
  it("returns 'Never' for null/undefined", () => {
    expect(formatRelativeTime(null)).toBe("Never");
    expect(formatRelativeTime(undefined)).toBe("Never");
  });

  it("describes a recent timestamp as 'just now'", () => {
    expect(formatRelativeTime(new Date().toISOString())).toBe("just now");
  });

  it("describes minutes, hours, and days ago", () => {
    const minutesAgo = new Date(Date.now() - 5 * 60 * 1000).toISOString();
    expect(formatRelativeTime(minutesAgo)).toBe("5m ago");

    const hoursAgo = new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString();
    expect(formatRelativeTime(hoursAgo)).toBe("3h ago");

    const daysAgo = new Date(Date.now() - 2 * 24 * 60 * 60 * 1000).toISOString();
    expect(formatRelativeTime(daysAgo)).toBe("2d ago");
  });
});

describe("formatDuration", () => {
  it("returns an em dash when duration is missing", () => {
    expect(formatDuration(null)).toBe("—");
    expect(formatDuration(undefined)).toBe("—");
  });

  it("formats sub-second durations in milliseconds", () => {
    expect(formatDuration(250)).toBe("250ms");
  });

  it("formats longer durations in seconds", () => {
    expect(formatDuration(1500)).toBe("1.5s");
  });
});

describe("getThumbnailUrl", () => {
  it("returns null when result is missing", () => {
    expect(getThumbnailUrl(null)).toBeNull();
    expect(getThumbnailUrl(undefined)).toBeNull();
  });

  it("returns null when neither known field is a string", () => {
    expect(getThumbnailUrl({ thumbnail_url: 42 })).toBeNull();
  });

  it("prefers thumbnail_url over image_url", () => {
    expect(
      getThumbnailUrl({ thumbnail_url: "a.jpg", image_url: "b.jpg" }),
    ).toBe("a.jpg");
  });

  it("falls back to image_url", () => {
    expect(getThumbnailUrl({ image_url: "b.jpg" })).toBe("b.jpg");
  });
});

describe("formatFileSize", () => {
  it("formats bytes below 1024 as B", () => {
    expect(formatFileSize(512)).toBe("512 B");
  });

  it("formats kilobytes", () => {
    expect(formatFileSize(340 * 1024)).toBe("340 KB");
  });

  it("formats megabytes with one decimal place", () => {
    expect(formatFileSize(1.2 * 1024 * 1024)).toBe("1.2 MB");
  });
});

describe("friendlyCommandLabel", () => {
  it("maps camera.snapshot to a friendly label", () => {
    expect(friendlyCommandLabel("camera.snapshot")).toBe("Snapshot Captured");
  });

  it("falls back to the raw command type when unmapped", () => {
    expect(friendlyCommandLabel("pump.start")).toBe("pump.start");
  });
});
