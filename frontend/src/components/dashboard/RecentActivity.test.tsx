import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { useCommand } from "@/hooks/useCommands";
import type { CommandDTO } from "@/types/api";
import { RecentActivity } from "./RecentActivity";

vi.mock("@/hooks/useCommands");

const mockedUseCommand = vi.mocked(useCommand);

function makeCommand(overrides: Partial<CommandDTO> = {}): CommandDTO {
  return {
    id: "cmd-1",
    device_id: "device-1",
    command_type: "pump.start",
    status: "COMPLETED",
    priority: "NORMAL",
    payload: {},
    requested_by: null,
    created_at: "2026-01-15T10:00:00Z",
    scheduled_at: null,
    started_at: null,
    completed_at: "2026-01-15T10:00:05Z",
    expires_at: null,
    correlation_id: "corr-1",
    trace_id: null,
    retry_count: 0,
    max_retries: 3,
    ...overrides,
  };
}

describe("RecentActivity", () => {
  it("shows an empty state when there is no activity", () => {
    mockedUseCommand.mockReturnValue({ data: undefined, isLoading: false } as unknown as ReturnType<
      typeof useCommand
    >);
    render(
      <MemoryRouter>
        <RecentActivity commands={[]} deviceNameById={{}} />
      </MemoryRouter>,
    );
    expect(screen.getByText("No activity yet.")).toBeInTheDocument();
  });

  it("only shows the 4 most recent activities", () => {
    mockedUseCommand.mockReturnValue({ data: undefined, isLoading: false } as unknown as ReturnType<
      typeof useCommand
    >);
    const commands = Array.from({ length: 5 }, (_, index) =>
      makeCommand({ id: `cmd-${index}`, command_type: `pump.start-${index}` }),
    );
    render(
      <MemoryRouter>
        <RecentActivity commands={commands} deviceNameById={{ "device-1": "Backyard Pi" }} />
      </MemoryRouter>,
    );
    expect(screen.getAllByText(/pump\.start-/)).toHaveLength(4);
  });

  it("expands an activity to show its detail on click", async () => {
    mockedUseCommand.mockReturnValue({
      data: {
        ...makeCommand(),
        result: {
          id: "result-1",
          success: true,
          exit_code: 0,
          result: {},
          error_message: null,
          duration_ms: 1200,
          completed_at: "2026-01-15T10:00:05Z",
        },
        events: [],
      },
      isLoading: false,
    } as unknown as ReturnType<typeof useCommand>);

    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <RecentActivity
          commands={[makeCommand()]}
          deviceNameById={{ "device-1": "Backyard Pi" }}
        />
      </MemoryRouter>,
    );

    await user.click(screen.getByText("pump.start"));
    expect(await screen.findByText("1.2s")).toBeInTheDocument();
  });
});
