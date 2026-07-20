/**
 * A third-party weather lookup, not a mirror of a server DTO (unlike
 * everything in @/types/api) — so its shape lives here instead. Calls
 * Open-Meteo (https://open-meteo.com) directly from the browser: free, no
 * API key, CORS-enabled, and open source, which is why it fits a
 * frontend-only widget with no backend/agent involvement.
 */

const OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast";

// Hardcoded for now, per the current single-location dashboard design —
// Pune, India (18.5204N, 73.8567E).
export const WEATHER_LOCATION = {
  name: "Pune, India",
  latitude: 18.5204,
  longitude: 73.8567,
  timezone: "Asia/Kolkata",
};

export interface WeatherDTO {
  /** WMO weather interpretation code (https://open-meteo.com/en/docs#weathervariables) for right now. */
  weatherCode: number;
  currentTemperatureC: number;
  highTemperatureC: number;
  lowTemperatureC: number;
}

interface OpenMeteoResponse {
  current_weather: { temperature: number; weathercode: number };
  daily: { temperature_2m_max: number[]; temperature_2m_min: number[] };
}

export async function getWeather(): Promise<WeatherDTO> {
  const url = new URL(OPEN_METEO_URL);
  url.searchParams.set("latitude", String(WEATHER_LOCATION.latitude));
  url.searchParams.set("longitude", String(WEATHER_LOCATION.longitude));
  url.searchParams.set("current_weather", "true");
  url.searchParams.set("daily", "temperature_2m_max,temperature_2m_min");
  url.searchParams.set("timezone", WEATHER_LOCATION.timezone);

  const response = await fetch(url.toString());
  if (!response.ok) {
    throw new Error(`Open-Meteo request failed: ${response.status}`);
  }
  const data = (await response.json()) as OpenMeteoResponse;

  return {
    weatherCode: data.current_weather.weathercode,
    currentTemperatureC: data.current_weather.temperature,
    highTemperatureC: data.daily.temperature_2m_max[0],
    lowTemperatureC: data.daily.temperature_2m_min[0],
  };
}
