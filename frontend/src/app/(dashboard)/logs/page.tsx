"use client";

import { useState } from "react";
import useSWR from "swr";
import toast from "react-hot-toast";
import api from "@/lib/api";
import type { QueryLog, PaginatedResponse } from "@/types";
import { Download, Search, RefreshCw } from "lucide-react";

const SOURCE_BADGE: Record<string, string> = {
  FAQ: "bg-green-100 text-green-700",
  "Discord History": "bg-indigo-100 text-indigo-700",
  "AI Reasoning": "bg-amber-100 text-amber-700",
  "AWS Documentation": "bg-orange-100 text-orange-700",
  "Multiple Sources": "bg-purple-100 text-purple-700",
  Unknown: "bg-gray-100 text-gray-600",
};

function exportToCsv(items: QueryLog[]) {
  const headers = [
    "timestamp",
    "user_name",
    "question",
    "source",
    "confidence",
    "response_time_ms",
    "channel_id",
  ];
  const rows = items.map((item) =>
    [
      item.timestamp,
      item.user_name,
      `"${item.question.replace(/"/g, '""')}"`,
      item.source,
      item.confidence,
      item.response_time_ms,
      item.channel_id,
    ].join(",")
  );
  const csv = [headers.join(","), ...rows].join("\n");
  const blob = new Blob([csv], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `besa-ai-logs-${Date.now()}.csv`;
  a.click();
  URL.revokeObjectURL(url);
  toast.success("Logs exported to CSV");
}

export default function LogsPage() {
  const [query, setQuery] = useState("");
  const [limit, setLimit] = useState(50);

  const { data, isLoading, mutate } = useSWR<PaginatedResponse<QueryLog>>(
    ["logs", limit],
    () => api.logs.queries(limit),
    { refreshInterval: 30000 }
  );

  const logs = data?.items ?? [];
  const filtered = query
    ? logs.filter(
        (l) =>
          l.question.toLowerCase().includes(query.toLowerCase()) ||
          l.user_name.toLowerCase().includes(query.toLowerCase()) ||
          l.source.toLowerCase().includes(query.toLowerCase())
      )
    : logs;

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Query Logs</h1>
          <p className="text-sm text-gray-500 mt-1">
            All questions asked via Discord. Retained for 90 days.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => mutate()}
            className="flex items-center gap-2 text-sm text-gray-600 hover:text-gray-900 border border-gray-200 hover:border-gray-300 px-3 py-2 rounded-lg transition"
          >
            <RefreshCw size={14} />
            Refresh
          </button>
          <button
            onClick={() => exportToCsv(filtered)}
            disabled={filtered.length === 0}
            className="flex items-center gap-2 text-sm text-white bg-blue-600 hover:bg-blue-700 px-3 py-2 rounded-lg transition disabled:opacity-50"
          >
            <Download size={14} />
            Export CSV
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex gap-4 mb-4">
        <div className="relative flex-1 max-w-md">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            placeholder="Search by question, user, or source..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="w-full pl-9 pr-4 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <select
          value={limit}
          onChange={(e) => setLimit(Number(e.target.value))}
          className="text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value={25}>25 rows</option>
          <option value={50}>50 rows</option>
          <option value={100}>100 rows</option>
          <option value={200}>200 rows</option>
        </select>
      </div>

      {/* Table */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
        {isLoading ? (
          <div className="flex items-center justify-center h-48">
            <div className="animate-spin h-5 w-5 border-2 border-blue-600 border-t-transparent rounded-full" />
          </div>
        ) : filtered.length === 0 ? (
          <div className="py-12 text-center text-gray-400 text-sm">
            No logs found. Questions will appear here after students ask them.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b border-gray-100">
                <tr>
                  {["Time", "User", "Question", "Source", "Confidence", "Response Time"].map(
                    (h) => (
                      <th
                        key={h}
                        className="text-left py-3 px-4 text-xs font-medium text-gray-500 uppercase tracking-wide"
                      >
                        {h}
                      </th>
                    )
                  )}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {filtered.map((log) => (
                  <tr key={log.log_id} className="hover:bg-gray-50 transition">
                    <td className="py-3 px-4 text-gray-500 text-xs whitespace-nowrap">
                      {new Date(log.timestamp).toLocaleString()}
                    </td>
                    <td className="py-3 px-4 font-medium text-gray-900">{log.user_name}</td>
                    <td className="py-3 px-4 max-w-xs">
                      <p className="text-gray-700 truncate" title={log.question}>
                        {log.question}
                      </p>
                    </td>
                    <td className="py-3 px-4">
                      <span
                        className={`px-2 py-1 rounded-full text-xs font-medium ${
                          SOURCE_BADGE[log.source] ?? SOURCE_BADGE.Unknown
                        }`}
                      >
                        {log.source}
                      </span>
                    </td>
                    <td className="py-3 px-4 text-gray-700">
                      {(parseFloat(log.confidence) * 100).toFixed(0)}%
                    </td>
                    <td className="py-3 px-4 text-gray-700">
                      {(log.response_time_ms / 1000).toFixed(1)}s
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <p className="text-xs text-gray-400 mt-2 text-right">
        Showing {filtered.length} of {logs.length} logs
      </p>
    </div>
  );
}
