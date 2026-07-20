import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { useNotificationStatus, useSendTestNotification } from "@/hooks/useNotifications";
import { NotificationsSettingsPage } from "./NotificationsSettingsPage";

vi.mock("@/hooks/useNotifications");

const mockedUseNotificationStatus = vi.mocked(useNotificationStatus);
const mockedUseSendTestNotification = vi.mocked(useSendTestNotification);

function renderPage() {
  return render(
    <MemoryRouter>
      <NotificationsSettingsPage />
    </MemoryRouter>,
  );
}

describe("NotificationsSettingsPage", () => {
  it("shows Telegram's current status when unconfigured", () => {
    mockedUseNotificationStatus.mockReturnValue({
      data: {
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
      },
      isLoading: false,
    } as unknown as ReturnType<typeof useNotificationStatus>);
    mockedUseSendTestNotification.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
      data: undefined,
    } as unknown as ReturnType<typeof useSendTestNotification>);

    renderPage();

    expect(screen.getByText("Disabled")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /send test notification/i })).toBeInTheDocument();
  });

  it("sends a test notification when the button is clicked", async () => {
    const mutate = vi.fn();
    mockedUseNotificationStatus.mockReturnValue({
      data: {
        providers: [
          {
            provider: "telegram",
            enabled: true,
            configured: true,
            last_attempt_at: null,
            last_success: null,
            last_error: null,
          },
        ],
      },
      isLoading: false,
    } as unknown as ReturnType<typeof useNotificationStatus>);
    mockedUseSendTestNotification.mockReturnValue({
      mutate,
      isPending: false,
      data: undefined,
    } as unknown as ReturnType<typeof useSendTestNotification>);

    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: /send test notification/i }));
    expect(mutate).toHaveBeenCalledOnce();
  });

  it("shows the result of a sent test notification", () => {
    mockedUseNotificationStatus.mockReturnValue({
      data: {
        providers: [
          {
            provider: "telegram",
            enabled: true,
            configured: true,
            last_attempt_at: "2026-01-15T10:00:00Z",
            last_success: false,
            last_error: "Telegram API returned 401: unauthorized",
          },
        ],
      },
      isLoading: false,
    } as unknown as ReturnType<typeof useNotificationStatus>);
    mockedUseSendTestNotification.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
      data: [{ provider: "telegram", success: false, duration_ms: 5, error_message: "boom" }],
    } as unknown as ReturnType<typeof useSendTestNotification>);

    renderPage();

    expect(screen.getByText(/boom/)).toBeInTheDocument();
    expect(screen.getByText(/Telegram API returned 401/)).toBeInTheDocument();
  });
});
