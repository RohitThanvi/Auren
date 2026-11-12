import { describe, expect, it } from "vitest";
import { loadEnv } from "./env";

const valid = { VITE_CLERK_PUBLISHABLE_KEY: "pk_test_abc", VITE_API_BASE_URL: "https://api.example.com" };

describe("loadEnv", () => {
  it("returns validated configuration", () => {
    expect(loadEnv(valid)).toEqual({
      clerkPublishableKey: "pk_test_abc",
      apiBaseUrl: "https://api.example.com",
    });
  });

  it("accepts http for local development", () => {
    expect(loadEnv({ ...valid, VITE_API_BASE_URL: "http://localhost:8000" }).apiBaseUrl).toBe(
      "http://localhost:8000",
    );
  });

  it.each([
    [{ ...valid, VITE_CLERK_PUBLISHABLE_KEY: "" }, "VITE_CLERK_PUBLISHABLE_KEY"],
    [{ ...valid, VITE_CLERK_PUBLISHABLE_KEY: "sk_live_secret" }, "VITE_CLERK_PUBLISHABLE_KEY"],
    [{ ...valid, VITE_API_BASE_URL: "not a url" }, "VITE_API_BASE_URL"],
    [{ ...valid, VITE_API_BASE_URL: "ftp://api.example.com" }, "VITE_API_BASE_URL"],
    [{ ...valid, VITE_API_BASE_URL: "https://api.example.com/" }, "VITE_API_BASE_URL"],
    [{}, "VITE_CLERK_PUBLISHABLE_KEY"],
  ])("rejects invalid configuration %#", (raw, field) => {
    expect(() => loadEnv(raw)).toThrow(field);
  });

  it("never echoes rejected values in the error", () => {
    expect(() => loadEnv({ ...valid, VITE_CLERK_PUBLISHABLE_KEY: "sk_live_secret" })).not.toThrow(
      /sk_live_secret/,
    );
  });
});
