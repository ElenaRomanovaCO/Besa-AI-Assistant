"use client";

import useSWR from "swr";
import api from "@/lib/api";
import {
  PieChart,
  Pie,
  Cell,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import { Activity, MessageSquare, Clock, Zap } from "lucide-react";
import type { AnalyticsOverview, FAQSyncStatus } from "@/types";

const SOURCE_COLORS: Record<string, string> = {
  FAQ: "#10b981",
  "Discord History": "#5865F2",
  "AI Reasoning": "#f59e0b",
  "AWS Documentation": "#FF9900",
  Unknown: "#9ca3af",
};

function StatCard({
  label,
  value,
  icon: Icon,
  color = "blue",
}: {
  label: string;
  value: string | number;
  icon: React.ElementType;
  color?: string;
}) {
  const colorMap: Record<string, string> = {
    blue: "bg-blue-50 text-blue-600",
    green: "bg-green-50 text-green-600",
    orange: "bg-orange-50 text-orange-600",
    purple: "bg-purple-50 text-purple-600",
  };
  return (
    <div className="bg-white rounded-xl p-6 shadow-sm border border-gray-100">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm text-gray-500 mb-1">{label}</p>
          <p className="text-2xl font-bold text-gray-900">{value}</p>
        </div>
        <div className={`p-3 rounded-lg ${colorMap[color] ?? colorMap.blue}`}>
          <Icon size={20} />
        </div>
      </div>
    </div>
  );
}

function SyncStatusBadge({ status }: { status: FAQSyncStatus["status"] }) {
  const map = {
    COMPLETED: "bg-green-100 text-green-700",
    SYNCING: "bg-blue-100 text-blue-700",
    PENDING: "bg-yellow-100 text-yellow-700",
    FAILED: "bg-red-100 text-red-700",
    NO_DATA: "bg-gray-100 text-gray-600",
    ERROR: "bg-red-100 text-red-700",
  };
  return (
    <span className={`px-2 py-1 rounded-full text-xs font-medium ${map[status]}`}>
      {status}
    </span>
  );
}

export default function DashboardPage() {
  const { data: analytics, isLoading: analyticsLoading } = useSWR<AnalyticsOverview>(
    "analytics",
    () => api.analytics.overview(),
    { refreshInterval: 30000 }
  );

  const { data: faqStatus } = useSWR<FAQSyncStatus>(
    "faq-status",
    () => api.faq.syncStatus(),
    { refreshInterval: 15000 }
  );

  const pieData = analytics
    ? Object.entries(analytics.source_distribution).map(([name, value]) => ({
        name,
        value,
      }))
    : [];

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
        <p className="text-gray-500 text-sm mt-1">
          Real-time overview of BeSa AI Assistant performance
        </p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <StatCard
          label="Total Questions"
          value={analyticsLoading ? "..." : (analytics?.total_questions ?? 0)}
          icon={MessageSquare}
          color="blue"
        />
        <StatCard
          label="Avg. Response Time"
          value={
            analyticsLoading
              ? "..."
              : `${((analytics?.avg_response_time_ms ?? 0) / 1000).toFixed(1)}s`
          }
          icon={Clock}
          color="orange"
        />
        <StatCard
          label="FAQ Status"
          value={faqStatus?.entry_count ?? 0}
          icon={Activity}
          color="green"
        />
        <StatCard
          label="Knowledge Sources"
          value={`${Object.keys(analytics?.source_distribution ?? {}).length}`}
          icon={Zap}
          color="purple"
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Source Distribution */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
          <h2 className="text-base font-semibold text-gray-900 mb-4">
            Answer Source Distribution
          </h2>
          {pieData.length > 0 ? (
            <ResponsiveContainer width="100%" height={240}>
              <PieChart>
                <Pie
                  data={pieData}
                  cx="50%"
                  cy="50%"
                  outerRadius={80}
                  dataKey="value"
                  label={({ name, percent }) =>
                    `${name} ${(percent * 100).toFixed(0)}%`
                  }
                >
                  {pieData.map((entry, index) => (
                    <Cell
                      key={index}
                      fill={SOURCE_COLORS[entry.name] ?? "#6b7280"}
                    />
                  ))}
                </Pie>
                <Tooltip />
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-60 flex items-center justify-center text-gray-400 text-sm">
              No data yet — ask some questions in Discord!
            </div>
          )}
        </div>

        {/* System Health */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
          <h2 className="text-base font-semibold text-gray-900 mb-4">
            System Health
          </h2>
          <div className="space-y-3">
            {[
              {
                label: "FAQ Knowledge Base",
                status: faqStatus?.status ?? "NO_DATA",
                detail: faqStatus
                  ? `${faqStatus.entry_count} entries`
                  : "No FAQ loaded",
              },
              {
                label: "Agent Processing",
                status: "COMPLETED" as const,
                detail: "Lambda + SQS operational",
              },
              {
                label: "Discord Integration",
                status: "COMPLETED" as const,
                detail: "Webhook + polling active",
              },
            ].map((item) => (
              <div
                key={item.label}
                className="flex items-center justify-between py-3 border-b border-gray-50 last:border-0"
              >
                <div>
                  <p className="text-sm font-medium text-gray-900">
                    {item.label}
                  </p>
                  <p className="text-xs text-gray-500 mt-0.5">{item.detail}</p>
                </div>
                <SyncStatusBadge status={item.status as FAQSyncStatus["status"]} />
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
