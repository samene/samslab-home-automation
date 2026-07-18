import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  CommandStatusBadge,
  DeviceStatusBadge,
  WorkflowRunStatusBadge,
  WorkflowStepRunStatusBadge,
} from "./StatusBadge";

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

describe("WorkflowRunStatusBadge", () => {
  it("renders a title-cased label for the workflow run status", () => {
    render(<WorkflowRunStatusBadge status="RUNNING" />);
    expect(screen.getByText("Running")).toBeInTheDocument();
  });

  it("renders every known workflow run status without throwing", () => {
    const statuses = ["RUNNING", "COMPLETED", "FAILED"] as const;
    for (const status of statuses) {
      const { unmount } = render(<WorkflowRunStatusBadge status={status} />);
      unmount();
    }
  });
});

describe("WorkflowStepRunStatusBadge", () => {
  it("renders a title-cased label for the workflow step run status", () => {
    render(<WorkflowStepRunStatusBadge status="CANCELLED" />);
    expect(screen.getByText("Cancelled")).toBeInTheDocument();
  });

  it("renders every known workflow step run status without throwing", () => {
    const statuses = ["PENDING", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"] as const;
    for (const status of statuses) {
      const { unmount } = render(<WorkflowStepRunStatusBadge status={status} />);
      unmount();
    }
  });
});
