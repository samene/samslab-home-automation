import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { useTheme } from "@/hooks/useTheme";
import { ThemeProvider } from "./ThemeContext";

function TestConsumer() {
  const { theme, setTheme } = useTheme();
  return (
    <div>
      <p>theme: {theme}</p>
      <button onClick={() => setTheme("light")}>Light</button>
      <button onClick={() => setTheme("dark")}>Dark</button>
    </div>
  );
}

describe("ThemeProvider", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.classList.remove("light", "dark");
  });

  it("defaults to light mode", () => {
    render(
      <ThemeProvider>
        <TestConsumer />
      </ThemeProvider>,
    );
    expect(screen.getByText("theme: light")).toBeInTheDocument();
    expect(document.documentElement.classList.contains("light")).toBe(true);
  });

  it("switches themes and persists the choice, updating the root class", async () => {
    const user = userEvent.setup();
    render(
      <ThemeProvider>
        <TestConsumer />
      </ThemeProvider>,
    );

    await user.click(screen.getByText("Light"));
    expect(screen.getByText("theme: light")).toBeInTheDocument();
    expect(document.documentElement.classList.contains("light")).toBe(true);
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    expect(localStorage.getItem("samslab.theme")).toBe("light");
  });

  it("reads a previously persisted theme on mount", () => {
    localStorage.setItem("samslab.theme", "light");
    render(
      <ThemeProvider>
        <TestConsumer />
      </ThemeProvider>,
    );
    expect(screen.getByText("theme: light")).toBeInTheDocument();
  });
});
