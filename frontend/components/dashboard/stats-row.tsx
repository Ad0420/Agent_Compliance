"use client";

import { useActions } from "@/hooks/use-actions";
import { useAgents } from "@/hooks/use-agents";
import { useCheckpoints } from "@/hooks/use-checkpoints";
import { Card, CardContent } from "@/components/ui/card";
import { Activity, Bot, Clock } from "lucide-react";
import { formatRelativeTime } from "@/lib/utils";

export function StatsRow() {
  const { data: actionsData } = useActions({ limit: 1 });
  const { data: agents } = useAgents();
  const { data: checkpoints } = useCheckpoints();

  const lastCheckpoint = checkpoints?.checkpoints?.[0];

  const stats = [
    {
      label: "Total Actions",
      value: actionsData?.total ?? "—",
      icon: Activity,
      description: "Records in chain",
    },
    {
      label: "Active Agents",
      value: agents?.length ?? "—",
      icon: Bot,
      description: "Registered agents",
    },
    {
      label: "Last Checkpoint",
      value: lastCheckpoint ? formatRelativeTime(lastCheckpoint.created_at) : "Never",
      icon: Clock,
      description: lastCheckpoint ? `Sequence ${lastCheckpoint.sequence_at_checkpoint}` : "No checkpoints yet",
    },
  ];

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
      {stats.map((stat) => (
        <Card key={stat.label}>
          <CardContent className="p-4">
            <div className="flex items-start justify-between">
              <div>
                <p className="text-xs font-medium text-muted-foreground">{stat.label}</p>
                <p className="mt-1 text-2xl font-bold">{stat.value}</p>
                <p className="mt-0.5 text-xs text-muted-foreground">{stat.description}</p>
              </div>
              <stat.icon className="h-5 w-5 text-muted-foreground/50" />
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
