import { Suspense } from "react";
import { Ga4View } from "./ga4-view";

export const metadata = { title: "GA4 · AI SEO Tool" };

export default function GscGa4Page({ params }: PageProps<"/gsc/[propertyId]/ga4">) {
  return (
    <div className="mx-auto max-w-6xl">
      <Suspense fallback={<p className="text-sm text-muted">Loading…</p>}>
        <Ga4View params={params} />
      </Suspense>
    </div>
  );
}
