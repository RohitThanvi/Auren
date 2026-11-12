import { Link } from "react-router-dom";

export function NotFoundPage() {
  return (
    <main className="mx-auto max-w-2xl space-y-2 p-8">
      <h1 className="text-2xl font-semibold">Page not found</h1>
      <Link className="underline" to="/">
        Back to home
      </Link>
    </main>
  );
}
