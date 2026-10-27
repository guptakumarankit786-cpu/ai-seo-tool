import { Suspense } from "react";
import { IntegrationsView } from "./integrations-view";

export const metadata = { title: "Integrations · AI SEO Tool" };

export default function IntegrationsPage() {
  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Integrations</h1>
        <p className="mt-1 text-sm text-muted">
          Every client we track, and whether we hold its data. Sync a client to pull its latest Search Console data.
        </p>
      </header>
      <Suspense fallback={<p className="text-sm text-muted">Loading…</p>}>
        <IntegrationsView />
      </Suspense>
    </div>
  );
}
