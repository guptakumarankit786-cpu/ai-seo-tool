import { Suspense } from "react";
import { KeywordsView } from "./keywords-view";

export const metadata = { title: "Keywords · AI SEO Tool" };

export default function GscKeywordsPage({ params }: PageProps<"/gsc/[propertyId]/keywords">) {
  return (
    <div className="mx-auto max-w-6xl">
      <Suspense fallback={<p className="text-sm text-muted">Loading…</p>}>
        <KeywordsView params={params} />
      </Suspense>
    </div>
  );
}
