import Link from "next/link";

const TABS = [
  { key: "performance", label: "Performance", path: "" },
  { key: "keywords", label: "Keywords", path: "/keywords" },
  { key: "pages", label: "Pages", path: "/pages" },
  { key: "indexing", label: "Indexing", path: "/indexing" },
] as const;

export function PropertyTabs({
  propertyId,
  active,
}: {
  propertyId: number;
  active: (typeof TABS)[number]["key"];
}) {
  return (
    <nav className="flex gap-1 border-b border-border" aria-label="Property sections">
      {TABS.map((tab) => (
        <Link
          key={tab.key}
          href={`/gsc/${propertyId}${tab.path}`}
          aria-current={active === tab.key ? "page" : undefined}
          className={`-mb-px border-b-2 px-3 py-2 text-sm ${
            active === tab.key
              ? "border-accent font-medium text-foreground"
              : "border-transparent text-muted hover:text-foreground"
          }`}
        >
          {tab.label}
        </Link>
      ))}
    </nav>
  );
}
