"use client";

import { useState, useTransition } from "react";
import { Button } from "@/components/ui/button";
import { Download, Loader2 } from "lucide-react";
import { toast } from "sonner";

/**
 * Triggers the proxy at `/api/dashboard/export/pdf` and saves the resulting
 * PDF blob via a temporary `<a>` element. We can't just `window.open(...)`
 * with Authorization header — instead we fetch the proxy (cookie-authed)
 * and save the response.
 */
export function ExportPdfButton({ range }: { range: string }) {
  const [downloading, setDownloading] = useState(false);
  const [, startTransition] = useTransition();

  const handleClick = () => {
    setDownloading(true);
    startTransition(async () => {
      try {
        const res = await fetch(
          `/api/dashboard/export/pdf?range=${encodeURIComponent(range)}`,
          { method: "GET" },
        );
        if (!res.ok) {
          let detail = `HTTP ${res.status}`;
          try {
            const body = await res.json();
            if (body && typeof body === "object" && "error" in body) {
              detail = String((body as { error: unknown }).error ?? detail);
            } else if (body && typeof body === "object" && "detail" in body) {
              detail = String((body as { detail: unknown }).detail ?? detail);
            }
          } catch {
            // ignore — keep status-based message
          }
          throw new Error(detail);
        }
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const cd = res.headers.get("content-disposition") ?? "";
        const match = /filename="?([^";]+)"?/i.exec(cd);
        const filename = match?.[1] ?? "vera_compliance_report.pdf";
        const a = document.createElement("a");
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
        toast.success("Evidence PDF downloaded");
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "PDF export failed";
        toast.error(message);
      } finally {
        setDownloading(false);
      }
    });
  };

  return (
    <Button
      type="button"
      onClick={handleClick}
      disabled={downloading}
      className="gap-1.5"
    >
      {downloading ? (
        <>
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          <span>Exporting…</span>
        </>
      ) : (
        <>
          <Download className="h-3.5 w-3.5" />
          <span>Export evidence (PDF)</span>
        </>
      )}
    </Button>
  );
}
