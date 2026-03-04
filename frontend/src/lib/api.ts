/**
 * API client for the BeSa AI Admin REST API.
 * All requests include the Cognito ID token for authorization.
 */

import { getIdToken } from "./auth";
import type {
  SystemConfig,
  FAQSyncStatus,
  FAQEntry,
  DiscordChannel,
  QueryLog,
  AnalyticsOverview,
  PaginatedResponse,
} from "@/types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

async function request<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const token = await getIdToken();
  if (!token) throw new Error("Not authenticated");

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      Authorization: token,
      ...options.headers,
    },
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ error: response.statusText }));
    throw new Error(error.error || `API error ${response.status}`);
  }

  return response.json() as Promise<T>;
}

// ---- Configuration ----

export const api = {
  config: {
    get: () => request<SystemConfig>("/api/configuration"),
    update: (data: Partial<SystemConfig>) =>
      request<{ message: string; config: SystemConfig }>("/api/configuration", {
        method: "PUT",
        body: JSON.stringify(data),
      }),
  },

  // ---- FAQ ----
  faq: {
    upload: (fileContent: string | ArrayBuffer, format: string) => {
      // All FAQ formats (csv, json, md) are text. Decode to a string so
      // API Gateway always sees a plain text body (avoids binary encoding issues).
      const body =
        fileContent instanceof ArrayBuffer
          ? new TextDecoder("utf-8").decode(fileContent)
          : fileContent;
      return request<{
        message: string;
        entry_count: number;
        sync_job_id: string;
        status: string;
      }>(`/api/faq/upload?format=${format}`, {
        method: "POST",
        body,
        headers: {
          "Content-Type": "text/plain",
        },
      });
    },
    syncStatus: () => request<FAQSyncStatus>("/api/faq/sync-status"),
    entries: () =>
      request<{ entries: FAQEntry[]; total: number }>("/api/faq/entries"),
  },

  // ---- Discord ----
  discord: {
    channels: () =>
      request<{ channels: DiscordChannel[] }>("/api/discord/channels"),
  },

  // ---- Logs ----
  logs: {
    queries: (limit = 50) =>
      request<PaginatedResponse<QueryLog>>(
        `/api/logs/queries?limit=${limit}`
      ),
  },

  // ---- Analytics ----
  analytics: {
    overview: () => request<AnalyticsOverview>("/api/analytics/overview"),
  },

  // ---- Rate Limits ----
  rateLimits: {
    reset: (userId: string) =>
      request<{ message: string }>("/api/rate-limits/reset", {
        method: "POST",
        body: JSON.stringify({ user_id: userId }),
      }),
  },
};

export default api;
