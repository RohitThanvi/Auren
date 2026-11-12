import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiConfigProvider } from "./api-config";
import { App } from "./App";

const auth = vi.hoisted(() => ({
  signedIn: false,
  getToken: vi.fn<() => Promise<string | null>>(() => Promise.resolve("tok_123")),
}));

vi.mock("@clerk/clerk-react", () => ({
  SignedIn: ({ children }: { children: React.ReactNode }) => (auth.signedIn ? children : null),
  SignedOut: ({ children }: { children: React.ReactNode }) => (auth.signedIn ? null : children),
  RedirectToSignIn: () => <div>redirecting to sign in</div>,
  SignInButton: ({ children }: { children: React.ReactNode }) => children,
  UserButton: () => <div>user menu</div>,
  useAuth: () => ({ getToken: auth.getToken, userId: auth.signedIn ? "user_1" : null }),
}));

function renderAt(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <ApiConfigProvider apiBaseUrl="https://api.example.com">
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[path]}>
          <App />
        </MemoryRouter>
      </QueryClientProvider>
    </ApiConfigProvider>,
  );
}

const ME = { id: "0b8c1f4e-5a77-4d0e-9a7b-3f3c2d1e9a10", roles: ["buyer", "provider"] };

describe("App", () => {
  beforeEach(() => {
    auth.signedIn = false;
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the public home page with a sign-in action when signed out", () => {
    renderAt("/");
    expect(screen.getByRole("heading", { name: "Auren" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign in" })).toBeInTheDocument();
  });

  it("links signed-in users to the dashboard", () => {
    auth.signedIn = true;
    renderAt("/");
    expect(screen.getByRole("link", { name: "Open dashboard" })).toHaveAttribute("href", "/dashboard");
  });

  it("redirects signed-out visitors away from the dashboard without calling the API", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    renderAt("/dashboard");
    expect(screen.getByText("redirecting to sign in")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("loads the signed-in user's roles from the API", async () => {
    auth.signedIn = true;
    const fetchMock = vi.fn(() => Promise.resolve(Response.json(ME)));
    vi.stubGlobal("fetch", fetchMock);
    renderAt("/dashboard");
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(await screen.findByText("buyer, provider")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "https://api.example.com/v1/me",
      expect.objectContaining({ credentials: "omit" }),
    );
  });

  it("shows a rate limit message on 429", async () => {
    auth.signedIn = true;
    const envelope = { error: { code: "rate_limited", message: "x", request_id: null, details: [] } };
    vi.stubGlobal("fetch", () => Promise.resolve(Response.json(envelope, { status: 429 })));
    renderAt("/dashboard");
    expect(await screen.findByRole("alert")).toHaveTextContent("Too many requests");
  });

  it("shows a generic message for other failures without leaking details", async () => {
    auth.signedIn = true;
    vi.stubGlobal("fetch", () => Promise.reject(new TypeError("secret internal detail")));
    renderAt("/dashboard");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("could not load your account");
    expect(alert).not.toHaveTextContent("secret internal detail");
  });

  it("renders a not-found page for unknown routes", () => {
    renderAt("/nope");
    expect(screen.getByRole("heading", { name: "Page not found" })).toBeInTheDocument();
  });
});
