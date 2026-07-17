import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { useAuth } from "@/hooks/useAuth";
import { ProtectedRoute } from "./ProtectedRoute";

vi.mock("@/hooks/useAuth");

const mockedUseAuth = vi.mocked(useAuth);

function renderProtected() {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route path="/login" element={<div>Login page</div>} />
        <Route
          path="/"
          element={
            <ProtectedRoute>
              <div>Secret dashboard</div>
            </ProtectedRoute>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ProtectedRoute", () => {
  it("renders nothing while auth status is loading", () => {
    mockedUseAuth.mockReturnValue({
      status: "loading",
      user: null,
      login: vi.fn(),
      logout: vi.fn(),
    });
    renderProtected();
    expect(screen.queryByText("Secret dashboard")).not.toBeInTheDocument();
    expect(screen.queryByText("Login page")).not.toBeInTheDocument();
  });

  it("redirects to /login when unauthenticated", () => {
    mockedUseAuth.mockReturnValue({
      status: "unauthenticated",
      user: null,
      login: vi.fn(),
      logout: vi.fn(),
    });
    renderProtected();
    expect(screen.getByText("Login page")).toBeInTheDocument();
  });

  it("renders children when authenticated", () => {
    mockedUseAuth.mockReturnValue({
      status: "authenticated",
      user: null,
      login: vi.fn(),
      logout: vi.fn(),
    });
    renderProtected();
    expect(screen.getByText("Secret dashboard")).toBeInTheDocument();
  });
});
