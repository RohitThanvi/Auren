import { describe, expect, it, vi } from "vitest";
import { ApiError, createApiClient } from "./client";
import { meResponseSchema } from "./schemas";

const ME = { id: "0b8c1f4e-5a77-4d0e-9a7b-3f3c2d1e9a10", roles: ["buyer"] };

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return Response.json(body, init);
}

function setup(response: Response | Error, token: string | null = "tok_123") {
  const fetchFn = vi.fn<typeof fetch>(() =>
    response instanceof Error ? Promise.reject(response) : Promise.resolve(response),
  );
  const client = createApiClient({
    baseUrl: "https://api.example.com",
    getToken: () => Promise.resolve(token),
    fetchFn,
  });
  return { client, fetchFn };
}

describe("api client", () => {
  it("sends the bearer token without cookies and parses the response", async () => {
    const { client, fetchFn } = setup(jsonResponse(ME));
    await expect(client.get("/v1/me", meResponseSchema)).resolves.toEqual(ME);

    const [url, init] = fetchFn.mock.calls[0] ?? [];
    expect(url).toBe("https://api.example.com/v1/me");
    expect(init?.credentials).toBe("omit");
    expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer tok_123");
  });

  it("omits Authorization when signed out", async () => {
    const { client, fetchFn } = setup(jsonResponse(ME), null);
    await client.get("/v1/me", meResponseSchema);
    expect(new Headers(fetchFn.mock.calls[0]?.[1]?.headers).has("Authorization")).toBe(false);
  });

  it("maps the API error envelope to ApiError, including Retry-After", async () => {
    const envelope = {
      error: { code: "rate_limited", message: "Too many requests.", request_id: "abc", details: [] },
    };
    const { client } = setup(jsonResponse(envelope, { status: 429, headers: { "Retry-After": "12" } }));
    const error = await client.get("/v1/me", meResponseSchema).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 429,
      code: "rate_limited",
      requestId: "abc",
      retryAfterSeconds: 12,
    });
  });

  it("falls back to a generic ApiError for non-envelope failures", async () => {
    const { client } = setup(new Response("<html>bad gateway</html>", { status: 502, statusText: "Bad Gateway" }));
    await expect(client.get("/v1/me", meResponseSchema)).rejects.toMatchObject({
      status: 502,
      code: "unknown_error",
      retryAfterSeconds: null,
    });
  });

  it("ignores a malformed Retry-After header", async () => {
    const { client } = setup(new Response("{}", { status: 503, headers: { "Retry-After": "soon" } }));
    await expect(client.get("/v1/me", meResponseSchema)).rejects.toMatchObject({
      retryAfterSeconds: null,
    });
  });

  it("rejects successful responses that violate the contract", async () => {
    const { client } = setup(jsonResponse({ id: "not-a-uuid", roles: ["superuser"] }));
    await expect(client.get("/v1/me", meResponseSchema)).rejects.toThrow();
  });

  it("propagates network failures and passes the abort signal", async () => {
    const { client, fetchFn } = setup(new TypeError("network down"));
    const controller = new AbortController();
    await expect(client.get("/v1/me", meResponseSchema, controller.signal)).rejects.toThrow(
      "network down",
    );
    expect(fetchFn.mock.calls[0]?.[1]?.signal).toBe(controller.signal);
  });
});
