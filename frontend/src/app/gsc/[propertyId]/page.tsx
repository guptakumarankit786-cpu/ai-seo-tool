import { Suspense } from "react";
import { PropertyDashboard } from "./property-dashboard";

export const metadata = { title: "Search Console · AI SEO Tool" };

export default function GscPropertyPage({ params }: PageProps<"/gsc/[propertyId]">) {
  return (
    <div className="mx-auto max-w-6xl">
      <Suspense fallback={<p className="text-sm text-muted">Loading…</p>}>
        <PropertyDashboard params={params} />
      </Suspense>
    </div>
  );
}
