import { useAuth } from "@clerk/clerk-react";
import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { useApiConfig } from "@/app/api-config";
import { createApiClient } from "@/lib/api/client";
import { meResponseSchema } from "@/lib/api/schemas";

export function useMe() {
  const { getToken, userId } = useAuth();
  const { apiBaseUrl } = useApiConfig();
  const client = useMemo(
    () => createApiClient({ baseUrl: apiBaseUrl, getToken }),
    [apiBaseUrl, getToken],
  );

  return useQuery({
    queryKey: ["me", userId],
    queryFn: ({ signal }) => client.get("/v1/me", meResponseSchema, signal),
    enabled: userId !== null && userId !== undefined,
  });
}
