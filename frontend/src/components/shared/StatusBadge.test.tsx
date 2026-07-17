import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CommandStatusBadge, DeviceStatusBadge } from "./StatusBadge";

describe("DeviceStatusBadge", () => {
  it("renders a title-cased label for the device status", () => {
    render(<DeviceStatusBadge status="ONLINE" />);
    expect(screen.getByText("Online")).toBeInTheDocument();
  });

  it("renders every known device status without throwing", () => {
    const statuses = [
      "REGISTERING",
      "ONLINE",
      "OFFLINE",
      "UNHEALTHY",
      "DISCONNECTED",
      "DISABLED",
      "UNKNOWN",
    ] as const;
    for (const status of statuses) {
      const { unmount } = render(<DeviceStatusBadge status={status} />);
      unmount();
    }
  });
});

describe("CommandStatusBadge", () => {
  it("renders a title-cased label for the command status", () => {
    render(<CommandStatusBadge status="COMPLETED" />);
    expect(screen.getByText("Completed")).toBeInTheDocument();
  });

  it("renders every known command status without throwing", () => {
    const statuses = [
      "PENDING",
      "QUEUED",
      "DISPATCHED",
      "RUNNING",
      "COMPLETED",
      "FAILED",
      "CANCELLED",
      "EXPIRED",
      "TIMEOUT",
    ] as const;
    for (const status of statuses) {
      const { unmount } = render(<CommandStatusBadge status={status} />);
      unmount();
    }
  });
});
