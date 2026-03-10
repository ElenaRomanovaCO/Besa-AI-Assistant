/**
 * API client for the BeSa AI Admin REST API.
 * All requests include the Cognito ID token for authorization.
 */

import { getIdToken } from "./auth";
import type {
  SystemConfig,
  FAQSyncStatus,
  FAQFile,
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
    upload: async (
      fileContent: string | ArrayBuffer,
      filename: string,
      overwrite = false
    ): Promise<{
      ok: boolean;
      status: number;
      data: Record<string, unknown>;
    }> => {
      const token = await getIdToken();
      if (!token) throw new Error("Not authenticated");
      const body =
        fileContent instanceof ArrayBuffer
          ? new TextDecoder("utf-8").decode(fileContent)
          : fileContent;
      const params = new URLSearchParams({ filename });
      if (overwrite) params.set("overwrite", "true");
      const response = await fetch(`${API_BASE}/api/faq/upload?${params}`, {
        method: "POST",
        headers: {
          "Content-Type": "text/plain",
          Authorization: token,
        },
        body,
      });
      const data = await response.json().catch(() => ({}));
      return { ok: response.ok, status: response.status, data };
    },
    syncStatus: () => request<FAQSyncStatus>("/api/faq/sync-status"),
    files: () =>
      request<{ files: FAQFile[]; total: number }>("/api/faq/files"),
    deleteFile: (filename: string) =>
      request<{ message: string }>(
        `/api/faq/files?filename=${encodeURIComponent(filename)}`,
        { method: "DELETE" }
      ),
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
