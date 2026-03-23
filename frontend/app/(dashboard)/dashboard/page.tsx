"use client";

import { ChainStatusCard } from "@/components/dashboard/chain-status-card";
import { StatsRow } from "@/components/dashboard/stats-row";
import { RecentActionsTable } from "@/components/dashboard/recent-actions-table";
import { ActionVolumeChart } from "@/components/dashboard/action-volume-chart";
import { GettingStarted } from "@/components/dashboard/getting-started";
import { useActions } from "@/hooks/use-actions";

export default function DashboardPage() {
  const { data } = useActions({ limit: 1 });
  const isEmpty = data?.total === 0;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Dashboard</h1>
        <p className="text-sm text-muted-foreground">Audit trail overview and chain integrity status</p>
      </div>

      {isEmpty && <GettingStarted />}

      <ChainStatusCard />
      <StatsRow />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <RecentActionsTable />
        <ActionVolumeChart />
      </div>
    </div>
  );
}
