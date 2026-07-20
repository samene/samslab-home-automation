import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import * as weatherApi from "@/lib/api/weather";
import type { WeatherDTO } from "@/lib/api/weather";
import { useWeather } from "./useWeather";

vi.mock("@/lib/api/weather", async () => {
  const actual = await vi.importActual<typeof weatherApi>("@/lib/api/weather");
  return { ...actual, getWeather: vi.fn() };
});

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

describe("useWeather", () => {
  it("fetches the current weather", async () => {
    const weather: WeatherDTO = {
      weatherCode: 0,
      currentTemperatureC: 30,
      highTemperatureC: 34,
      lowTemperatureC: 21,
    };
    vi.mocked(weatherApi.getWeather).mockResolvedValue(weather);

    const { result } = renderHook(() => useWeather(), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(weather);
  });
});
