import { Suspense } from "react";
import { IndexingView } from "./indexing-view";

export const metadata = { title: "Indexing · AI SEO Tool" };

export default function GscIndexingPage({ params }: PageProps<"/gsc/[propertyId]/indexing">) {
  return (
    <div className="mx-auto max-w-6xl">
      <Suspense fallback={<p className="text-sm text-muted">Loading…</p>}>
        <IndexingView params={params} />
      </Suspense>
    </div>
  );
}
