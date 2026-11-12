import type { z } from "zod";
import { errorResponseSchema } from "./schemas";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly requestId: string | null,
    readonly retryAfterSeconds: number | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export interface ApiClientOptions {
  baseUrl: string;
  /** Returns a Clerk session token, or null when signed out. */
  getToken: () => Promise<string | null>;
  fetchFn?: typeof fetch;
}

export interface ApiClient {
  get: <T>(path: string, schema: z.ZodType<T>, signal?: AbortSignal) => Promise<T>;
}

function parseRetryAfter(header: string | null): number | null {
  if (header === null || !/^\d+$/.test(header)) return null;
  return Number(header);
}

export function createApiClient({
  baseUrl,
  getToken,
  fetchFn = fetch,
}: ApiClientOptions): ApiClient {
  async function get<T>(path: string, schema: z.ZodType<T>, signal?: AbortSignal): Promise<T> {
    const token = await getToken();
    const headers = new Headers({ Accept: "application/json" });
    if (token !== null) headers.set("Authorization", `Bearer ${token}`);

    const response = await fetchFn(`${baseUrl}${path}`, {
      method: "GET",
      headers,
      credentials: "omit",
      ...(signal ? { signal } : {}),
    });

    const body: unknown = await response.json().catch(() => null);
    if (!response.ok) {
      const parsed = errorResponseSchema.safeParse(body);
      const retryAfter = parseRetryAfter(response.headers.get("Retry-After"));
      if (parsed.success) {
        const { code, message, request_id } = parsed.data.error;
        throw new ApiError(response.status, code, message, request_id, retryAfter);
      }
      throw new ApiError(response.status, "unknown_error", response.statusText, null, retryAfter);
    }
    return schema.parse(body);
  }

  return { get };
}
