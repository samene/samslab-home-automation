import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useWeather } from "@/hooks/useWeather";
import { WeatherWidget } from "./WeatherWidget";

vi.mock("@/hooks/useWeather");

const mockedUseWeather = vi.mocked(useWeather);

describe("WeatherWidget", () => {
  it("shows the location, current temperature, and today's high/low", () => {
    mockedUseWeather.mockReturnValue({
      data: { weatherCode: 0, currentTemperatureC: 30.2, highTemperatureC: 34.1, lowTemperatureC: 21.6 },
      isLoading: false,
      isError: false,
    } as unknown as ReturnType<typeof useWeather>);

    render(<WeatherWidget />);

    expect(screen.getByText("Pune, India")).toBeInTheDocument();
    expect(screen.getByText("Clear")).toBeInTheDocument();
    expect(screen.getByText("30°")).toBeInTheDocument();
    expect(screen.getByText(/H: 34°/)).toBeInTheDocument();
    expect(screen.getByText(/L: 22°/)).toBeInTheDocument();
  });

  it("labels a rainy weather code correctly", () => {
    mockedUseWeather.mockReturnValue({
      data: { weatherCode: 63, currentTemperatureC: 24, highTemperatureC: 27, lowTemperatureC: 20 },
      isLoading: false,
      isError: false,
    } as unknown as ReturnType<typeof useWeather>);

    render(<WeatherWidget />);

    expect(screen.getByText("Rain")).toBeInTheDocument();
  });

  it("shows a loading state while fetching", () => {
    mockedUseWeather.mockReturnValue({
      data: undefined,
      isLoading: true,
      isError: false,
    } as unknown as ReturnType<typeof useWeather>);

    render(<WeatherWidget />);

    expect(screen.queryByText("Pune, India")).not.toBeInTheDocument();
  });

  it("shows a fallback message when the request fails", () => {
    mockedUseWeather.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
    } as unknown as ReturnType<typeof useWeather>);

    render(<WeatherWidget />);

    expect(screen.getByText("Pune, India")).toBeInTheDocument();
    expect(screen.getByText("Weather unavailable.")).toBeInTheDocument();
  });
});
