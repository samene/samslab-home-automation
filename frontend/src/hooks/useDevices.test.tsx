import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import * as devicesApi from "@/lib/api/devices";
import type { DeviceDTO, DevicePageDTO } from "@/types/api";
import { useDevice, useDevices, usePrimaryDevice } from "./useDevices";

vi.mock("@/lib/api/devices");

const DEVICE: DeviceDTO = {
  id: "device-1",
  device_name: "backyard-pi",
  hostname: "backyard-pi.local",
  display_name: "Backyard Pi",
  description: null,
  status: "ONLINE",
  last_seen: null,
  agent_version: null,
  protocol_version: null,
  registered_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  enabled: true,
  metadata: {},
  capabilities: [],
};

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

describe("useDevices", () => {
  it("fetches the device list", async () => {
    const page: DevicePageDTO = { items: [DEVICE], total: 1, offset: 0, limit: 50 };
    vi.mocked(devicesApi.listDevices).mockResolvedValue(page);

    const { result } = renderHook(() => useDevices(), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(page);
  });
});

describe("useDevice", () => {
  it("does not fetch when no deviceId is given", () => {
    const { result } = renderHook(() => useDevice(undefined), { wrapper });
    expect(result.current.fetchStatus).toBe("idle");
    expect(devicesApi.getDevice).not.toHaveBeenCalled();
  });

  it("fetches a single device once given an id", async () => {
    vi.mocked(devicesApi.getDevice).mockResolvedValue(DEVICE);
    const { result } = renderHook(() => useDevice("device-1"), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(devicesApi.getDevice).toHaveBeenCalledWith("device-1");
    expect(result.current.data).toEqual(DEVICE);
  });
});

describe("usePrimaryDevice", () => {
  it("returns the first device from the list", async () => {
    vi.mocked(devicesApi.listDevices).mockResolvedValue({
      items: [DEVICE],
      total: 1,
      offset: 0,
      limit: 1,
    });

    const { result } = renderHook(() => usePrimaryDevice(), { wrapper });

    await waitFor(() => expect(result.current.data).toEqual(DEVICE));
  });

  it("returns undefined when there are no devices", async () => {
    vi.mocked(devicesApi.listDevices).mockResolvedValue({
      items: [],
      total: 0,
      offset: 0,
      limit: 1,
    });

    const { result } = renderHook(() => usePrimaryDevice(), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toBeUndefined();
  });
});
