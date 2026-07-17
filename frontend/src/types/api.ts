/**
 * TypeScript mirrors of the server's application-layer DTOs
 * (server/app/application/dto/*.py). Kept as plain types, not classes —
 * these are wire shapes, not behavior.
 */

export type DeviceStatus =
  | "REGISTERING"
  | "ONLINE"
  | "OFFLINE"
  | "UNHEALTHY"
  | "DISCONNECTED"
  | "DISABLED"
  | "UNKNOWN";

export type CommandStatus =
  | "PENDING"
  | "QUEUED"
  | "DISPATCHED"
  | "RUNNING"
  | "COMPLETED"
  | "FAILED"
  | "CANCELLED"
  | "EXPIRED"
  | "TIMEOUT";

export type CommandPriority = "LOW" | "NORMAL" | "HIGH" | "CRITICAL";

export type CommandEventType =
  | "COMMAND_CREATED"
  | "COMMAND_DISPATCHED"
  | "COMMAND_STARTED"
  | "COMMAND_COMPLETED"
  | "COMMAND_FAILED"
  | "COMMAND_CANCELLED"
  | "COMMAND_EXPIRED"
  | "COMMAND_TIMEOUT"
  | "COMMAND_RETRY_SCHEDULED";

export interface CapabilityDTO {
  id: string;
  capability: string;
  version: string;
  configuration: Record<string, unknown>;
}

export interface DeviceDTO {
  id: string;
  device_name: string;
  hostname: string;
  display_name: string;
  description: string | null;
  status: DeviceStatus;
  last_seen: string | null;
  agent_version: string | null;
  protocol_version: string | null;
  registered_at: string;
  updated_at: string;
  enabled: boolean;
  metadata: Record<string, unknown>;
  capabilities: CapabilityDTO[];
}

export interface DevicePageDTO {
  items: DeviceDTO[];
  total: number;
  offset: number;
  limit: number;
}

export interface CommandResultDTO {
  id: string;
  success: boolean;
  exit_code: number | null;
  result: Record<string, unknown>;
  error_message: string | null;
  duration_ms: number | null;
  completed_at: string;
}

export interface CommandEventDTO {
  id: string;
  event_type: CommandEventType;
  timestamp: string;
  details: Record<string, unknown>;
}

export interface CommandDTO {
  id: string;
  device_id: string;
  command_type: string;
  status: CommandStatus;
  priority: CommandPriority;
  payload: Record<string, unknown>;
  requested_by: string | null;
  created_at: string;
  scheduled_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  expires_at: string | null;
  correlation_id: string;
  trace_id: string | null;
  retry_count: number;
  max_retries: number;
}

export interface CommandDetailDTO extends CommandDTO {
  result: CommandResultDTO | null;
  events: CommandEventDTO[];
}

export interface CommandPageDTO {
  items: CommandDTO[];
  total: number;
  offset: number;
  limit: number;
}

export interface CommandCreateRequest {
  device_id: string;
  command_type: string;
  payload?: Record<string, unknown>;
  priority?: CommandPriority;
  requested_by?: string;
  max_retries?: number;
}

export interface LoginRequest {
  username: string;
  password: string;
}

export interface RefreshRequest {
  refresh_token: string;
}

export interface TokenPairDTO {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
  expires_in: number;
}

export interface UserDTO {
  id: string;
  username: string;
  email: string;
  enabled: boolean;
  roles: string[];
  created_at: string;
  updated_at: string;
  last_login: string | null;
}

export interface HealthStatusDTO {
  status: "ok" | "unhealthy";
}

export interface ServiceInfoDTO extends HealthStatusDTO {
  service: string;
}

export interface DispatcherStatusDTO {
  running: boolean;
  started_at: string | null;
  queue_depth: number;
  pending_ack_count: number;
  running_count: number;
  poll_interval_seconds: number;
}

export interface DispatcherStatisticsDTO {
  commands_dispatched_total: number;
  dispatch_failures_total: number;
  dispatcher_retries_total: number;
  dispatcher_timeouts_total: number;
  queue_depth: number;
  pending_ack_count: number;
  running_count: number;
}

export interface CameraStatusDTO {
  running: boolean;
  stream_name: string;
  playback_url: string;
  playback_token: string | null;
  resolution: string | null;
  fps: number | null;
  started_at: string | null;
  uptime_seconds: number;
  viewer_count: number;
}

export interface CameraStopDTO {
  status: string;
  duration_seconds: number | null;
  frames_sent: number | null;
  stopped_at: string | null;
}

export interface ApiProblem {
  type: string;
  title: string;
  status: number;
  detail: string;
  instance?: string;
  trace_id?: string;
}
