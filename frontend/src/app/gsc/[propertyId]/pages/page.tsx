import { Suspense } from "react";
import { PagesView } from "./pages-view";

export const metadata = { title: "Pages · AI SEO Tool" };

export default function GscPagesPage({ params }: PageProps<"/gsc/[propertyId]/pages">) {
  return (
    <div className="mx-auto max-w-6xl">
      <Suspense fallback={<p className="text-sm text-muted">Loading…</p>}>
        <PagesView params={params} />
      </Suspense>
    </div>
  );
}
