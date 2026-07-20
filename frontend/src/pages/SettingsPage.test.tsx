import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { useAuth } from "@/hooks/useAuth";
import { useServiceInfo } from "@/hooks/useHealth";
import { useTheme } from "@/hooks/useTheme";
import { SettingsPage } from "./SettingsPage";

vi.mock("@/hooks/useAuth");
vi.mock("@/hooks/useTheme");
vi.mock("@/hooks/useHealth");

const mockedUseAuth = vi.mocked(useAuth);
const mockedUseTheme = vi.mocked(useTheme);
const mockedUseServiceInfo = vi.mocked(useServiceInfo);

function renderSettingsPage() {
  return render(
    <MemoryRouter>
      <SettingsPage />
    </MemoryRouter>,
  );
}

describe("SettingsPage", () => {
  it("shows the current user's profile and lets them log out", async () => {
    const logout = vi.fn();
    mockedUseAuth.mockReturnValue({
      status: "authenticated",
      user: {
        id: "user-1",
        username: "sam",
        email: "sam@example.com",
        enabled: true,
        roles: ["Admin"],
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
        last_login: null,
      },
      login: vi.fn(),
      logout,
    });
    mockedUseTheme.mockReturnValue({ theme: "dark", setTheme: vi.fn() });
    mockedUseServiceInfo.mockReturnValue({ data: undefined } as unknown as ReturnType<typeof useServiceInfo>);

    const user = userEvent.setup();
    renderSettingsPage();

    expect(screen.getByText("sam")).toBeInTheDocument();
    expect(screen.getByText("sam@example.com")).toBeInTheDocument();
    expect(screen.getByText("Admin")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /log out/i }));
    expect(logout).toHaveBeenCalledOnce();
  });

  it("toggles the theme switch", async () => {
    const setTheme = vi.fn();
    mockedUseAuth.mockReturnValue({ status: "authenticated", user: null, login: vi.fn(), logout: vi.fn() });
    mockedUseTheme.mockReturnValue({ theme: "dark", setTheme });
    mockedUseServiceInfo.mockReturnValue({ data: undefined } as unknown as ReturnType<typeof useServiceInfo>);

    const user = userEvent.setup();
    renderSettingsPage();

    await user.click(screen.getByRole("switch"));
    expect(setTheme).toHaveBeenCalledWith("light");
  });

  it("displays server information once loaded", () => {
    mockedUseAuth.mockReturnValue({ status: "authenticated", user: null, login: vi.fn(), logout: vi.fn() });
    mockedUseTheme.mockReturnValue({ theme: "dark", setTheme: vi.fn() });
    mockedUseServiceInfo.mockReturnValue({
      data: { status: "ok", service: "samslab-cloud" },
    } as unknown as ReturnType<typeof useServiceInfo>);

    renderSettingsPage();

    expect(screen.getByText("ok")).toBeInTheDocument();
    expect(screen.getByText("samslab-cloud")).toBeInTheDocument();
  });

  it("shows the pump's GPIO configuration", () => {
    mockedUseAuth.mockReturnValue({ status: "authenticated", user: null, login: vi.fn(), logout: vi.fn() });
    mockedUseTheme.mockReturnValue({ theme: "dark", setTheme: vi.fn() });
    mockedUseServiceInfo.mockReturnValue({ data: undefined } as unknown as ReturnType<typeof useServiceInfo>);

    renderSettingsPage();

    expect(screen.getByText(/PUMP_GPIO_PIN/)).toBeInTheDocument();
    expect(screen.getByText(/PUMP_ACTIVE_HIGH/)).toBeInTheDocument();
    expect(screen.getByText(/PUMP_TRIGGER_PULSE_MS/)).toBeInTheDocument();
  });

  it("links to the Notifications settings page", () => {
    mockedUseAuth.mockReturnValue({ status: "authenticated", user: null, login: vi.fn(), logout: vi.fn() });
    mockedUseTheme.mockReturnValue({ theme: "dark", setTheme: vi.fn() });
    mockedUseServiceInfo.mockReturnValue({ data: undefined } as unknown as ReturnType<typeof useServiceInfo>);

    renderSettingsPage();

    const link = screen.getByRole("link", { name: /manage notifications/i });
    expect(link).toHaveAttribute("href", "/settings/notifications");
  });
});
