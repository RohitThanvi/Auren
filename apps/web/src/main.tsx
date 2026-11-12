import { ClerkProvider } from "@clerk/clerk-react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { ApiConfigProvider } from "@/app/api-config";
import { App } from "@/app/App";
import { loadEnv } from "@/config/env";
import { ApiError } from "@/lib/api/client";
import "./index.css";

const env = loadEnv(import.meta.env);

const MAX_RETRIES = 2;
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Client errors (401, 403, 404, 429...) will not succeed on retry; only retry transient failures.
      retry: (failureCount, error) =>
        !(error instanceof ApiError && error.status < 500) && failureCount < MAX_RETRIES,
    },
  },
});

const container = document.getElementById("root");
if (container === null) throw new Error("Root element #root not found");

createRoot(container).render(
  <StrictMode>
    <ClerkProvider publishableKey={env.clerkPublishableKey} afterSignOutUrl="/">
      <ApiConfigProvider apiBaseUrl={env.apiBaseUrl}>
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <App />
          </BrowserRouter>
        </QueryClientProvider>
      </ApiConfigProvider>
    </ClerkProvider>
  </StrictMode>,
);
