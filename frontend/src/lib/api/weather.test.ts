import { afterEach, describe, expect, it, vi } from "vitest";
import { getWeather, WEATHER_LOCATION } from "./weather";

function mockFetchOnce(body: unknown, ok = true) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok,
      status: ok ? 200 : 500,
      json: () => Promise.resolve(body),
    }),
  );
}

describe("weather api", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("requests Open-Meteo for the hardcoded Pune location", async () => {
    mockFetchOnce({
      current_weather: { temperature: 28.4, weathercode: 1 },
      daily: { temperature_2m_max: [33.1], temperature_2m_min: [22.7] },
    });

    await getWeather();

    const calledUrl = new URL(vi.mocked(fetch).mock.calls[0][0] as string);
    expect(calledUrl.origin + calledUrl.pathname).toBe("https://api.open-meteo.com/v1/forecast");
    expect(calledUrl.searchParams.get("latitude")).toBe(String(WEATHER_LOCATION.latitude));
    expect(calledUrl.searchParams.get("longitude")).toBe(String(WEATHER_LOCATION.longitude));
    expect(calledUrl.searchParams.get("current_weather")).toBe("true");
  });

  it("maps the Open-Meteo response into a WeatherDTO", async () => {
    mockFetchOnce({
      current_weather: { temperature: 28.4, weathercode: 61 },
      daily: { temperature_2m_max: [33.1], temperature_2m_min: [22.7] },
    });

    const result = await getWeather();

    expect(result).toEqual({
      weatherCode: 61,
      currentTemperatureC: 28.4,
      highTemperatureC: 33.1,
      lowTemperatureC: 22.7,
    });
  });

  it("throws when the request fails", async () => {
    mockFetchOnce({}, false);

    await expect(getWeather()).rejects.toThrow("Open-Meteo request failed: 500");
  });
});
