import { notFound } from "next/navigation";

/**
 * Dev-only route group.
 *
 * Pages inside `(dev)/` are visual previews of component primitives —
 * they are not part of the production surface and must 404 in production
 * builds. The `notFound()` call below short-circuits SSR before the layout
 * renders any markup when `NODE_ENV === 'production'`.
 *
 * The route group itself is `(dev)` rather than `/dev` so it doesn't show
 * up in the URL path — preview pages live at `/components-preview` etc.
 * directly. That's deliberate: in development, you want short URLs to
 * navigate to; in production, the entire group is gone.
 */
export default function DevLayout({ children }: { children: React.ReactNode }) {
  if (process.env.NODE_ENV === "production") {
    notFound();
  }

  return (
    <div className="dashboard min-h-screen bg-background text-foreground">
      {children}
    </div>
  );
}
