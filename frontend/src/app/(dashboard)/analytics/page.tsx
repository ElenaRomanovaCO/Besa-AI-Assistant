"use client";

import useSWR from "swr";
import api from "@/lib/api";
import type { AnalyticsOverview } from "@/types";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  Legend,
} from "recharts";

const SOURCE_COLORS: Record<string, string> = {
  FAQ: "#10b981",
  "Discord History": "#5865F2",
  "AI Reasoning": "#f59e0b",
  "AWS Documentation": "#FF9900",
  Unknown: "#9ca3af",
};

function MetricCard({ label, value, unit }: { label: string; value: string | number; unit?: string }) {
  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
      <p className="text-sm text-gray-500">{label}</p>
      <p className="text-3xl font-bold text-gray-900 mt-1">
        {value}
        {unit && <span className="text-base font-normal text-gray-500 ml-1">{unit}</span>}
      </p>
    </div>
  );
}

export default function AnalyticsPage() {
  const { data: analytics, isLoading } = useSWR<AnalyticsOverview>(
    "analytics-detail",
    () => api.analytics.overview(),
    { refreshInterval: 60000 }
  );

  const sourceDistData = analytics
    ? Object.entries(analytics.source_distribution).map(([name, value]) => ({
        name,
        value,
        pct: analytics.total_questions > 0
          ? Math.round((value / analytics.total_questions) * 100)
          : 0,
      }))
    : [];

  if (isLoading) {
    return (
      <div className="p-6 flex items-center justify-center h-64">
        <div className="animate-spin h-6 w-6 border-2 border-blue-600 border-t-transparent rounded-full" />
      </div>
    );
  }

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Analytics</h1>
        <p className="text-sm text-gray-500 mt-1">
          Usage statistics and performance metrics for the AI assistant.
        </p>
      </div>

      {/* Key Metrics */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-8">
        <MetricCard
          label="Total Questions"
          value={analytics?.total_questions ?? 0}
        />
        <MetricCard
          label="Avg. Response Time"
          value={((analytics?.avg_response_time_ms ?? 0) / 1000).toFixed(1)}
          unit="seconds"
        />
        <MetricCard
          label="Knowledge Sources Active"
          value={Object.keys(analytics?.source_distribution ?? {}).length}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Source Distribution — Bar Chart */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
          <h2 className="text-base font-semibold text-gray-900 mb-4">
            Answers by Source
          </h2>
          {sourceDistData.length > 0 ? (
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={sourceDistData} layout="vertical" margin={{ left: 16 }}>
                <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 12 }} />
                <YAxis
                  type="category"
                  dataKey="name"
                  tick={{ fontSize: 11 }}
                  width={120}
                />
                <Tooltip
                  formatter={(value, _name, props) => [
                    `${value} (${props.payload.pct}%)`,
                    "Questions",
                  ]}
                />
                <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                  {sourceDistData.map((entry, i) => (
                    <Cell
                      key={i}
                      fill={SOURCE_COLORS[entry.name] ?? "#6b7280"}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-60 flex items-center justify-center text-gray-400 text-sm">
              No data yet
            </div>
          )}
        </div>

        {/* Source Distribution — Pie Chart */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
          <h2 className="text-base font-semibold text-gray-900 mb-4">
            Source Distribution
          </h2>
          {sourceDistData.length > 0 ? (
            <ResponsiveContainer width="100%" height={260}>
              <PieChart>
                <Pie
                  data={sourceDistData}
                  cx="50%"
                  cy="50%"
                  outerRadius={90}
                  dataKey="value"
                  label={({ pct }) => `${pct}%`}
                >
                  {sourceDistData.map((entry, i) => (
                    <Cell key={i} fill={SOURCE_COLORS[entry.name] ?? "#6b7280"} />
                  ))}
                </Pie>
                <Tooltip formatter={(v) => [v, "Questions"]} />
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-60 flex items-center justify-center text-gray-400 text-sm">
              No data yet
            </div>
          )}
        </div>
      </div>

      {/* Source breakdown table */}
      {sourceDistData.length > 0 && (
        <div className="mt-6 bg-white rounded-xl shadow-sm border border-gray-100 p-6">
          <h2 className="text-base font-semibold text-gray-900 mb-4">Source Breakdown</h2>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100">
                <th className="text-left py-2 text-xs font-medium text-gray-500 uppercase">Source</th>
                <th className="text-right py-2 text-xs font-medium text-gray-500 uppercase">Questions</th>
                <th className="text-right py-2 text-xs font-medium text-gray-500 uppercase">Share</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {sourceDistData.map((row) => (
                <tr key={row.name}>
                  <td className="py-3">
                    <div className="flex items-center gap-2">
                      <div
                        className="w-3 h-3 rounded-full"
                        style={{ backgroundColor: SOURCE_COLORS[row.name] ?? "#6b7280" }}
                      />
                      {row.name}
                    </div>
                  </td>
                  <td className="py-3 text-right font-medium">{row.value}</td>
                  <td className="py-3 text-right text-gray-500">{row.pct}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
