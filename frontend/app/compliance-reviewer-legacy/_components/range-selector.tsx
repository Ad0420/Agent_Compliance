"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useTransition } from "react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const OPTIONS = [
  { value: "7", label: "Last 7 days" },
  { value: "30", label: "Last 30 days" },
  { value: "90", label: "Last 90 days" },
  { value: "180", label: "Last 180 days" },
];

/**
 * Time-window selector for the compliance dashboard. Writes the chosen
 * number of days into `?range=` on the URL — which is what makes the
 * saved-view URLs work. Push as a fresh URL so the back button takes the
 * user to the previous window.
 */
export function RangeSelector({ value }: { value: string }) {
  const router = useRouter();
  const search = useSearchParams();
  const [isPending, startTransition] = useTransition();

  const onChange = (next: string) => {
    const params = new URLSearchParams(search?.toString() ?? "");
    params.set("range", next);
    startTransition(() => {
      router.push(`/compliance-reviewer-legacy?${params.toString()}`);
    });
  };

  return (
    <Select value={value} onValueChange={onChange} disabled={isPending}>
      <SelectTrigger className="w-[160px]" aria-label="Time range">
        <SelectValue placeholder="Last 30 days" />
      </SelectTrigger>
      <SelectContent>
        {OPTIONS.map((o) => (
          <SelectItem key={o.value} value={o.value}>
            {o.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
