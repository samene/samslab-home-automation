import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { DeviceDTO } from "@/types/api";
import { DeviceHeroCard } from "./DeviceHeroCard";

const DEVICE: DeviceDTO = {
  id: "device-1",
  device_name: "backyard-pi",
  hostname: "backyard-pi.local",
  display_name: "Backyard Pi",
  description: null,
  status: "ONLINE",
  last_seen: new Date().toISOString(),
  agent_version: "1.2.0",
  protocol_version: "1",
  registered_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  enabled: true,
  metadata: {},
  capabilities: [],
};

describe("DeviceHeroCard", () => {
  it("shows an empty state when there is no device", () => {
    render(<DeviceHeroCard device={undefined} />);
    expect(screen.getByText("No devices registered yet.")).toBeInTheDocument();
  });

  it("shows the device's name, status, heartbeat, and agent version", () => {
    render(<DeviceHeroCard device={DEVICE} />);

    expect(screen.getByText("Backyard Pi")).toBeInTheDocument();
    expect(screen.getByText("Online")).toBeInTheDocument();
    expect(screen.getByText("1.2.0")).toBeInTheDocument();
  });
});
