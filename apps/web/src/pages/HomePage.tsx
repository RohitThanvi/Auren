import { SignedIn, SignedOut, SignInButton } from "@clerk/clerk-react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";

export function HomePage() {
  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col justify-center gap-6 p-8">
      <h1 className="text-3xl font-semibold">Auren</h1>
      <p className="text-muted-foreground">
        A marketplace for renting idle CPU, RAM, GPU and storage from independent providers.
      </p>
      <div>
        <SignedOut>
          <SignInButton mode="modal">
            <Button>Sign in</Button>
          </SignInButton>
        </SignedOut>
        <SignedIn>
          <Button asChild>
            <Link to="/dashboard">Open dashboard</Link>
          </Button>
        </SignedIn>
      </div>
    </main>
  );
}
