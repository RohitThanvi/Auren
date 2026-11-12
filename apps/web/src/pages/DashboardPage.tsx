import { UserButton } from "@clerk/clerk-react";
import { useMe } from "@/features/me/useMe";
import { ApiError } from "@/lib/api/client";

export function DashboardPage() {
  const me = useMe();

  return (
    <main className="mx-auto max-w-2xl space-y-4 p-8">
      <header className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Dashboard</h1>
        <UserButton />
      </header>
      {me.isPending ? <p role="status">Loading your account…</p> : null}
      {me.isError ? (
        <p role="alert" className="text-destructive">
          {me.error instanceof ApiError && me.error.code === "rate_limited"
            ? "Too many requests. Please wait a moment and try again."
            : "We could not load your account. Please try again."}
        </p>
      ) : null}
      {me.isSuccess ? (
        <p>
          Your roles: <strong>{me.data.roles.join(", ")}</strong>
        </p>
      ) : null}
    </main>
  );
}
