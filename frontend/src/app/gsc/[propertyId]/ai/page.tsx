import { Suspense } from "react";
import { AiView } from "./ai-view";

export const metadata = { title: "AI traffic · AI SEO Tool" };

export default function GscAiPage({ params }: PageProps<"/gsc/[propertyId]/ai">) {
  return (
    <div className="mx-auto max-w-6xl">
      <Suspense fallback={<p className="text-sm text-muted">Loading…</p>}>
        <AiView params={params} />
      </Suspense>
    </div>
  );
}
