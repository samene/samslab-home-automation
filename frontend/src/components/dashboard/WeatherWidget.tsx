import {
  Cloud,
  CloudDrizzle,
  CloudFog,
  CloudLightning,
  CloudRain,
  CloudSnow,
  CloudSun,
  MapPin,
  Sun,
  type LucideIcon,
} from "lucide-react";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useWeather } from "@/hooks/useWeather";
import { WEATHER_LOCATION } from "@/lib/api/weather";
import { cn } from "@/lib/utils";

interface Condition {
  label: string;
  icon: LucideIcon;
  /** Tinted, theme-aware gradient standing in for "a background that matches the weather." */
  gradient: string;
  iconClassName: string;
}

/** WMO weather codes (https://open-meteo.com/en/docs#weathervariables), grouped into the handful of conditions this widget distinguishes visually. */
function conditionForCode(code: number): Condition {
  if (code === 0) {
    return {
      label: "Clear",
      icon: Sun,
      gradient: "bg-gradient-to-br from-amber-300/40 to-orange-400/15 dark:from-amber-500/25 dark:to-orange-600/10",
      iconClassName: "text-amber-500",
    };
  }
  if (code === 1 || code === 2) {
    return {
      label: "Partly Cloudy",
      icon: CloudSun,
      gradient: "bg-gradient-to-br from-sky-300/35 to-amber-300/15 dark:from-sky-500/20 dark:to-amber-500/10",
      iconClassName: "text-sky-500",
    };
  }
  if (code === 3) {
    return {
      label: "Overcast",
      icon: Cloud,
      gradient: "bg-gradient-to-br from-slate-300/40 to-slate-400/15 dark:from-slate-500/25 dark:to-slate-600/10",
      iconClassName: "text-slate-500",
    };
  }
  if (code === 45 || code === 48) {
    return {
      label: "Fog",
      icon: CloudFog,
      gradient: "bg-gradient-to-br from-gray-300/40 to-gray-400/15 dark:from-gray-500/25 dark:to-gray-600/10",
      iconClassName: "text-gray-500",
    };
  }
  if ([51, 53, 55, 56, 57].includes(code)) {
    return {
      label: "Drizzle",
      icon: CloudDrizzle,
      gradient: "bg-gradient-to-br from-blue-300/35 to-slate-400/15 dark:from-blue-500/20 dark:to-slate-600/10",
      iconClassName: "text-blue-500",
    };
  }
  if ([61, 63, 65, 66, 67, 80, 81, 82].includes(code)) {
    return {
      label: "Rain",
      icon: CloudRain,
      gradient: "bg-gradient-to-br from-blue-400/40 to-blue-600/15 dark:from-blue-500/25 dark:to-blue-700/10",
      iconClassName: "text-blue-600",
    };
  }
  if ([71, 73, 75, 77, 85, 86].includes(code)) {
    return {
      label: "Snow",
      icon: CloudSnow,
      gradient: "bg-gradient-to-br from-sky-200/40 to-sky-300/15 dark:from-sky-400/20 dark:to-sky-500/10",
      iconClassName: "text-sky-400",
    };
  }
  if ([95, 96, 99].includes(code)) {
    return {
      label: "Thunderstorm",
      icon: CloudLightning,
      gradient: "bg-gradient-to-br from-purple-400/40 to-indigo-600/15 dark:from-purple-500/25 dark:to-indigo-700/10",
      iconClassName: "text-purple-500",
    };
  }
  return {
    label: "Cloudy",
    icon: Cloud,
    gradient: "bg-gradient-to-br from-slate-300/40 to-slate-400/15 dark:from-slate-500/25 dark:to-slate-600/10",
    iconClassName: "text-slate-500",
  };
}

function formatTemperature(celsius: number): string {
  return `${Math.round(celsius)}°`;
}

/** Self-contained, mirroring how CameraPanel/RecentMedia fetch their own data internally. */
export function WeatherWidget() {
  const { data, isLoading, isError } = useWeather();

  if (isLoading) {
    return (
      <Card className="flex shrink-0 flex-col gap-2 p-3">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-12 w-full" />
      </Card>
    );
  }

  if (isError || !data) {
    return (
      <Card className="flex shrink-0 flex-col gap-1 p-3">
        <div className="flex items-center gap-1 text-xs font-semibold">
          <MapPin className="size-3.5" />
          {WEATHER_LOCATION.name}
        </div>
        <p className="px-1 py-1 text-xs text-muted-foreground">Weather unavailable.</p>
      </Card>
    );
  }

  const condition = conditionForCode(data.weatherCode);
  const Icon = condition.icon;

  return (
    <Card className={cn("flex shrink-0 flex-col gap-2 overflow-hidden p-3", condition.gradient)}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1 text-xs font-semibold">
          <MapPin className="size-3.5" />
          {WEATHER_LOCATION.name}
        </div>
        <span className="text-xs text-muted-foreground">{condition.label}</span>
      </div>

      <div className="flex items-center justify-between">
        <Icon className={cn("size-9", condition.iconClassName)} />
        <div className="flex flex-col items-end">
          <span className="text-2xl font-semibold tabular-nums">
            {formatTemperature(data.currentTemperatureC)}
          </span>
          <span className="text-xs tabular-nums text-muted-foreground">
            H: {formatTemperature(data.highTemperatureC)} · L: {formatTemperature(data.lowTemperatureC)}
          </span>
        </div>
      </div>
    </Card>
  );
}
