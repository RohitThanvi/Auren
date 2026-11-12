import { createContext, useContext, type ReactNode } from "react";

interface ApiConfig {
  apiBaseUrl: string;
}

const ApiConfigContext = createContext<ApiConfig | null>(null);

export function ApiConfigProvider({ apiBaseUrl, children }: ApiConfig & { children: ReactNode }) {
  return <ApiConfigContext value={{ apiBaseUrl }}>{children}</ApiConfigContext>;
}

// eslint-disable-next-line react-refresh/only-export-components -- hook colocated with its provider
export function useApiConfig(): ApiConfig {
  const config = useContext(ApiConfigContext);
  if (config === null) throw new Error("useApiConfig must be used inside ApiConfigProvider");
  return config;
}
