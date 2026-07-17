import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { useAuth } from "@/hooks/useAuth";
import { LoginPage } from "./LoginPage";

vi.mock("@/hooks/useAuth");

const mockedUseAuth = vi.mocked(useAuth);

describe("LoginPage", () => {
  it("submits the entered credentials", async () => {
    const login = vi.fn().mockResolvedValue(undefined);
    mockedUseAuth.mockReturnValue({ status: "unauthenticated", user: null, login, logout: vi.fn() });

    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>,
    );

    await user.type(screen.getByLabelText("Username"), "sam");
    await user.type(screen.getByLabelText("Password"), "secret");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() =>
      expect(login).toHaveBeenCalledWith({ username: "sam", password: "secret" }),
    );
  });

  it("shows an error message when login fails", async () => {
    const login = vi.fn().mockRejectedValue(new Error("Invalid username or password"));
    mockedUseAuth.mockReturnValue({ status: "unauthenticated", user: null, login, logout: vi.fn() });

    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>,
    );

    await user.type(screen.getByLabelText("Username"), "sam");
    await user.type(screen.getByLabelText("Password"), "wrong");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    expect(await screen.findByText("Invalid username or password")).toBeInTheDocument();
  });

  it("redirects away when already authenticated", () => {
    mockedUseAuth.mockReturnValue({
      status: "authenticated",
      user: null,
      login: vi.fn(),
      logout: vi.fn(),
    });

    render(
      <MemoryRouter initialEntries={["/login"]}>
        <LoginPage />
      </MemoryRouter>,
    );

    expect(screen.queryByRole("button", { name: /sign in/i })).not.toBeInTheDocument();
  });
});
