import { Suspense } from "react";
import { PageDetailView } from "./page-detail-view";

export const metadata = { title: "Page · AI SEO Tool" };

export default function GscPageDetailPage({ params }: PageProps<"/gsc/[propertyId]/pages/detail">) {
  return (
    <div className="mx-auto max-w-6xl">
      <Suspense fallback={<p className="text-sm text-muted">Loading…</p>}>
        <PageDetailView params={params} />
      </Suspense>
    </div>
  );
}
