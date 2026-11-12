import type { components } from "@auren/contracts";
import { z } from "zod";

// Runtime validators for API responses. Each is type-checked against the generated contract so
// a backend change that is not reflected here fails `npm run typecheck`.

export const meResponseSchema = z.object({
  id: z.uuid(),
  roles: z.array(z.enum(["buyer", "provider", "admin"])),
}) satisfies z.ZodType<components["schemas"]["MeResponse"]>;

export const errorResponseSchema = z.object({
  error: z.object({
    code: z.string(),
    message: z.string(),
    request_id: z.string().nullable(),
    details: z.array(
      z.object({ location: z.array(z.string()), message: z.string(), type: z.string() }),
    ),
  }),
}) satisfies z.ZodType<components["schemas"]["ErrorResponse"]>;
