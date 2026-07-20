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

export interface CameraSnapshotDTO {
  id: string;
  device_id: string;
  command_id: string;
  filename: string;
  width: number;
  height: number;
  size: number;
  captured_at: string;
}

export type MediaType = "IMAGE" | "VIDEO";

export interface SavedMediaDTO {
  id: string;
  media_type: MediaType;
  device_id: string;
  command_id: string;
  filename: string;
  thumbnail_url: string;
  image_url: string;
  video_url: string;
  etag: string | null;
  sha256: string;
  width: number;
  height: number;
  duration: number | null;
  fps: number | null;
  bitrate: number | null;
  size: number;
  captured_at: string;
  created_at: string;
  metadata: Record<string, unknown>;
  workflow_id: string | null;
  workflow_name: string | null;
}

export interface SavedMediaPageDTO {
  items: SavedMediaDTO[];
  total: number;
  offset: number;
  limit: number;
}

export type WorkflowStepType = "COMMAND" | "SLEEP" | "GROUP";
export type WorkflowGroupMode = "SERIAL" | "PARALLEL";
export type WorkflowRunStatus = "RUNNING" | "COMPLETED" | "FAILED";
export type WorkflowStepRunStatus = "PENDING" | "RUNNING" | "COMPLETED" | "FAILED" | "CANCELLED";

export interface WorkflowStepDTO {
  id: string;
  step_type: WorkflowStepType;
  command_type: string | null;
  sleep_seconds: number | null;
  group_mode: WorkflowGroupMode | null;
  children: WorkflowStepDTO[];
}

export interface WorkflowDTO {
  id: string;
  name: string;
  description: string | null;
  enabled: boolean;
  run_count: number;
  last_run_at: string | null;
  last_run_status: WorkflowRunStatus | null;
  last_run_duration_ms: number | null;
  created_at: string;
  updated_at: string;
}

export interface WorkflowPageDTO {
  items: WorkflowDTO[];
  total: number;
  offset: number;
  limit: number;
}

export interface WorkflowStepRunDTO {
  id: string | null;
  workflow_step_id: string;
  step_type: WorkflowStepType;
  status: WorkflowStepRunStatus;
  started_at: string | null;
  completed_at: string | null;
  command_id: string | null;
  error_message: string | null;
  children: WorkflowStepRunDTO[];
}

export interface WorkflowRunDTO {
  id: string;
  workflow_id: string;
  status: WorkflowRunStatus;
  started_at: string;
  completed_at: string | null;
  error_message: string | null;
  step_runs: WorkflowStepRunDTO[];
}

export interface WorkflowDetailDTO extends WorkflowDTO {
  steps: WorkflowStepDTO[];
  latest_run: WorkflowRunDTO | null;
}

export interface WorkflowStepCreateRequest {
  step_type: WorkflowStepType;
  command_type?: string | null;
  sleep_seconds?: number | null;
  group_mode?: WorkflowGroupMode | null;
  children?: WorkflowStepCreateRequest[];
}

export interface WorkflowCreateRequest {
  name: string;
  description?: string | null;
  enabled?: boolean;
  steps: WorkflowStepCreateRequest[];
}

export type ScheduleType = "ONE_TIME" | "CRON";
export type ScheduleRunStatus = "RUNNING" | "COMPLETED" | "FAILED";

export interface ScheduleDTO {
  id: string;
  workflow_id: string;
  workflow_name: string | null;
  name: string;
  description: string | null;
  enabled: boolean;
  schedule_type: ScheduleType;
  cron_expression: string | null;
  run_at: string | null;
  timezone: string;
  run_count: number;
  last_run_at: string | null;
  next_run_at: string | null;
  last_status: ScheduleRunStatus | null;
  created_at: string;
  updated_at: string;
}

export interface SchedulePageDTO {
  items: ScheduleDTO[];
  total: number;
  offset: number;
  limit: number;
}

export interface ScheduleCreateRequest {
  workflow_id: string;
  name: string;
  description?: string | null;
  enabled?: boolean;
  schedule_type: ScheduleType;
  cron_expression?: string | null;
  run_at?: string | null;
  timezone?: string;
}

export interface ScheduleExecutionDTO {
  id: string;
  schedule_id: string;
  schedule_name: string | null;
  workflow_id: string;
  workflow_run_id: string | null;
  triggered_at: string;
  status: ScheduleRunStatus;
  error_message: string | null;
}

export interface ScheduleExecutionPageDTO {
  items: ScheduleExecutionDTO[];
  total: number;
  offset: number;
  limit: number;
}

export interface ApiProblem {
  type: string;
  title: string;
  status: number;
  detail: string;
  instance?: string;
  trace_id?: string;
}
