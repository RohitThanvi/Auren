import { z } from "zod";

const envSchema = z.object({
  VITE_CLERK_PUBLISHABLE_KEY: z.string().startsWith("pk_", "must be a Clerk publishable key"),
  VITE_API_BASE_URL: z
    .url({ protocol: /^https?$/ })
    .refine((value) => !value.endsWith("/"), "must not end with a slash"),
});

export interface AppEnv {
  clerkPublishableKey: string;
  apiBaseUrl: string;
}

/** Validates build-time configuration once at startup and fails loudly if it is wrong. */
export function loadEnv(raw: Record<string, unknown>): AppEnv {
  const parsed = envSchema.safeParse(raw);
  if (!parsed.success) {
    const problems = parsed.error.issues
      .map((issue) => `${issue.path.join(".")}: ${issue.message}`)
      .join("; ");
    throw new Error(`Invalid frontend environment: ${problems}`);
  }
  return {
    clerkPublishableKey: parsed.data.VITE_CLERK_PUBLISHABLE_KEY,
    apiBaseUrl: parsed.data.VITE_API_BASE_URL,
  };
}
