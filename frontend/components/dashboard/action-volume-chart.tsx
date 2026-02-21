"use client";

import { useMemo } from "react";
import { useActions } from "@/hooks/use-actions";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import { format, subDays, startOfDay } from "date-fns";

export function ActionVolumeChart() {
  const { data } = useActions({ limit: 200 });

  const chartData = useMemo(() => {
    const days: Record<string, number> = {};
    // Initialize last 14 days
    for (let i = 13; i >= 0; i--) {
      const day = format(startOfDay(subDays(new Date(), i)), "MMM d");
      days[day] = 0;
    }

    if (data?.records) {
      for (const record of data.records) {
        const day = format(new Date(record.action_timestamp), "MMM d");
        if (day in days) {
          days[day]++;
        }
      }
    }

    return Object.entries(days).map(([date, count]) => ({ date, count }));
  }, [data]);

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Action Volume</CardTitle>
        <p className="text-xs text-muted-foreground">Last 14 days</p>
      </CardHeader>
      <CardContent>
        <div className="h-48">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chartData}>
              <defs>
                <linearGradient id="colorCount" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis
                dataKey="date"
                tick={{ fontSize: 11, fill: "#888" }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                tick={{ fontSize: 11, fill: "#888" }}
                axisLine={false}
                tickLine={false}
                allowDecimals={false}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: "#1a1a1a",
                  border: "1px solid #333",
                  borderRadius: "8px",
                  fontSize: "12px",
                }}
              />
              <Area
                type="monotone"
                dataKey="count"
                stroke="#3b82f6"
                fill="url(#colorCount)"
                strokeWidth={2}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  );
}
