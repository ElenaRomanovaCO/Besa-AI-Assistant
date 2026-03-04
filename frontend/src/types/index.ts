// ============================================================
// BeSa AI Admin UI — shared TypeScript types
// ============================================================

// ---- System Configuration ----

export interface ThresholdConfig {
  faq_threshold: number;
  discord_threshold: number;
  query_expansion_depth: number;
  max_faq_results: number;
  max_discord_results: number;
}

export interface AgentConfig {
  enable_faq_agent: boolean;
  enable_discord_agent: boolean;
  enable_reasoning_agent: boolean;
  enable_aws_docs_agent: boolean;
  enable_online_search_agent: boolean;
}

export interface RateLimitConfig {
  max_queries_per_hour: number;
}

export interface SystemConfig {
  config_id: string;
  faq_threshold: string;
  discord_threshold: string;
  query_expansion_depth: number;
  max_faq_results: number;
  max_discord_results: number;
  enable_faq_agent: boolean;
  enable_discord_agent: boolean;
  enable_reasoning_agent: boolean;
  enable_aws_docs_agent: boolean;
  enable_online_search_agent: boolean;
  max_queries_per_hour: number;
  searchable_channel_ids: string[];
  log_retention_days: number;
  cost_alert_threshold_usd: string;
  updated_at: string;
  updated_by: string;
}

// ---- FAQ ----

export interface FAQEntry {
  id: string;
  s3_key: string;
  size: number;
  last_modified: string;
}

export interface FAQSyncStatus {
  status: "PENDING" | "SYNCING" | "COMPLETED" | "FAILED" | "NO_DATA" | "ERROR";
  entry_count: number;
  sync_job_id?: string;
  last_updated?: string;
  uploaded_by?: string;
  error?: string;
}

// ---- Discord ----

export interface DiscordChannel {
  channel_id: string;
  name: string;
  type: number;
  topic?: string;
  is_selected: boolean;
}

// ---- Query Logs ----

export type QuerySource =
  | "FAQ"
  | "Discord History"
  | "AI Reasoning"
  | "AWS Documentation"
  | "Multiple Sources"
  | "Unknown";

export interface QueryLog {
  log_id: string;
  timestamp: string;
  user_id: string;
  user_name: string;
  question: string;
  source: QuerySource;
  confidence: string;
  response_time_ms: number;
  channel_id: string;
  guild_id: string;
  waterfall_steps: string[];
  correlation_id: string;
}

// ---- Analytics ----

export interface AnalyticsOverview {
  total_questions: number;
  source_distribution: Record<string, number>;
  avg_response_time_ms: number;
}

// ---- API responses ----

export interface ApiError {
  error: string;
  message?: string;
}

export interface PaginatedResponse<T> {
  items: T[];
  count: number;
  last_evaluated_key?: Record<string, unknown>;
}
