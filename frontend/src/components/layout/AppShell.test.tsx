import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { useAuth } from "@/hooks/useAuth";
import { useTheme } from "@/hooks/useTheme";
import { AppShell } from "./AppShell";

vi.mock("@/hooks/useAuth");
vi.mock("@/hooks/useTheme");

const mockedUseAuth = vi.mocked(useAuth);
const mockedUseTheme = vi.mocked(useTheme);

describe("AppShell", () => {
  it("renders navigation links and the children content", () => {
    mockedUseAuth.mockReturnValue({
      status: "authenticated",
      user: { id: "1", username: "sam", email: "sam@example.com", enabled: true, roles: [], created_at: "", updated_at: "", last_login: null },
      login: vi.fn(),
      logout: vi.fn(),
    });
    mockedUseTheme.mockReturnValue({ theme: "dark", setTheme: vi.fn() });

    render(
      <MemoryRouter>
        <AppShell>
          <p>Page content</p>
        </AppShell>
      </MemoryRouter>,
    );

    expect(screen.getAllByText("Dashboard").length).toBeGreaterThan(0);
    expect(screen.getAllByText("History").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Settings").length).toBeGreaterThan(0);
    expect(screen.getByText("Page content")).toBeInTheDocument();
  });

  it("toggles the theme when the theme button is clicked", async () => {
    const setTheme = vi.fn();
    mockedUseAuth.mockReturnValue({
      status: "authenticated",
      user: null,
      login: vi.fn(),
      logout: vi.fn(),
    });
    mockedUseTheme.mockReturnValue({ theme: "dark", setTheme });

    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <AppShell>
          <p>Page content</p>
        </AppShell>
      </MemoryRouter>,
    );

    await user.click(screen.getByRole("button", { name: /toggle theme/i }));
    expect(setTheme).toHaveBeenCalledWith("light");
  });

  it("logs out from the user menu", async () => {
    const logout = vi.fn();
    mockedUseAuth.mockReturnValue({
      status: "authenticated",
      user: { id: "1", username: "sam", email: "sam@example.com", enabled: true, roles: [], created_at: "", updated_at: "", last_login: null },
      login: vi.fn(),
      logout,
    });
    mockedUseTheme.mockReturnValue({ theme: "dark", setTheme: vi.fn() });

    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <AppShell>
          <p>Page content</p>
        </AppShell>
      </MemoryRouter>,
    );

    await user.click(screen.getByText("SA"));
    await user.click(await screen.findByText("Log out"));
    expect(logout).toHaveBeenCalledOnce();
  });
});
