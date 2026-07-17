import { isAxiosError } from "axios";
import type { ApiProblem } from "@/types/api";

/** Extract a human-readable message from an RFC 7807 problem+json error response. */
export function getErrorMessage(error: unknown, fallback = "Something went wrong."): string {
  if (isAxiosError<ApiProblem>(error)) {
    return error.response?.data?.detail ?? error.message ?? fallback;
  }
  if (error instanceof Error) return error.message;
  return fallback;
}
