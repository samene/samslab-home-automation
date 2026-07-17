import { AxiosError } from "axios";
import { describe, expect, it } from "vitest";
import { getErrorMessage } from "./errors";

describe("getErrorMessage", () => {
  it("extracts the RFC 7807 detail field from an axios error", () => {
    const error = new AxiosError("Request failed");
    error.response = {
      data: { detail: "Invalid credentials" },
      status: 401,
      statusText: "Unauthorized",
      headers: {},
      config: {} as never,
    };
    expect(getErrorMessage(error)).toBe("Invalid credentials");
  });

  it("falls back to the axios error message when there's no response body", () => {
    const error = new AxiosError("Network Error");
    expect(getErrorMessage(error)).toBe("Network Error");
  });

  it("uses a plain Error's message", () => {
    expect(getErrorMessage(new Error("boom"))).toBe("boom");
  });

  it("uses the fallback for unrecognized error shapes", () => {
    expect(getErrorMessage("nope", "fallback message")).toBe("fallback message");
  });
});
