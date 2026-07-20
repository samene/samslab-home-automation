import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import * as notificationsApi from "@/lib/api/notifications";
import type { NotificationStatusDTO, TestNotificationResultDTO } from "@/types/api";
import { useNotificationStatus, useSendTestNotification } from "./useNotifications";

vi.mock("@/lib/api/notifications");
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

describe("useNotificationStatus", () => {
  it("fetches provider status", async () => {
    const status: NotificationStatusDTO = {
      providers: [
        {
          provider: "telegram",
          enabled: false,
          configured: false,
          last_attempt_at: null,
          last_success: null,
          last_error: null,
        },
      ],
    };
    vi.mocked(notificationsApi.getNotificationStatus).mockResolvedValue(status);

    const { result } = renderHook(() => useNotificationStatus(), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(status);
  });
});

describe("useSendTestNotification", () => {
  it("sends a test notification and returns per-provider results", async () => {
    const results: TestNotificationResultDTO[] = [
      { provider: "telegram", success: true, duration_ms: 12, error_message: null },
    ];
    vi.mocked(notificationsApi.sendTestNotification).mockResolvedValue(results);

    const { result } = renderHook(() => useSendTestNotification(), { wrapper });
    result.current.mutate();

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(results);
  });
});
