"use client";

import { useState, useEffect } from "react";
import useSWR from "swr";
import toast from "react-hot-toast";
import api from "@/lib/api";
import type { SystemConfig } from "@/types";

function SliderField({
  label,
  description,
  value,
  min,
  max,
  step,
  onChange,
}: {
  label: string;
  description: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (v: number) => void;
}) {
  return (
    <div className="py-4 border-b border-gray-100 last:border-0">
      <div className="flex items-center justify-between mb-2">
        <div>
          <p className="text-sm font-medium text-gray-900">{label}</p>
          <p className="text-xs text-gray-500 mt-0.5">{description}</p>
        </div>
        <span className="text-sm font-semibold text-blue-600 bg-blue-50 px-3 py-1 rounded-full">
          {step < 1 ? value.toFixed(2) : value}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-blue-600"
      />
      <div className="flex justify-between text-xs text-gray-400 mt-1">
        <span>{min}</span>
        <span>{max}</span>
      </div>
    </div>
  );
}

function Toggle({
  label,
  description,
  checked,
  onChange,
}: {
  label: string;
  description: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between py-3 border-b border-gray-100 last:border-0">
      <div>
        <p className="text-sm font-medium text-gray-900">{label}</p>
        <p className="text-xs text-gray-500 mt-0.5">{description}</p>
      </div>
      <button
        type="button"
        onClick={() => onChange(!checked)}
        className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
          checked ? "bg-blue-600" : "bg-gray-200"
        }`}
      >
        <span
          className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
            checked ? "translate-x-6" : "translate-x-1"
          }`}
        />
      </button>
    </div>
  );
}

export default function ConfigurationPage() {
  const { data: config, mutate, isLoading } = useSWR<SystemConfig>(
    "config",
    () => api.config.get()
  );

  const [form, setForm] = useState<Partial<SystemConfig>>({});
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (config) setForm(config);
  }, [config]);

  async function handleSave() {
    setSaving(true);
    try {
      const updated = await api.config.update({
        faq_threshold: form.faq_threshold,
        discord_threshold: form.discord_threshold,
        query_expansion_depth: form.query_expansion_depth,
        enable_faq_agent: form.enable_faq_agent,
        enable_discord_agent: form.enable_discord_agent,
        enable_reasoning_agent: form.enable_reasoning_agent,
        enable_aws_docs_agent: form.enable_aws_docs_agent,
        enable_online_search_agent: form.enable_online_search_agent,
        max_queries_per_hour: form.max_queries_per_hour,
      });
      await mutate(updated.config);
      toast.success("Configuration saved");
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  if (isLoading) {
    return (
      <div className="p-6 flex items-center justify-center h-64">
        <div className="animate-spin h-6 w-6 border-2 border-blue-600 border-t-transparent rounded-full" />
      </div>
    );
  }

  return (
    <div className="p-6 max-w-3xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Configuration</h1>
          <p className="text-sm text-gray-500 mt-1">
            Adjust waterfall thresholds and agent settings. Changes apply immediately.
          </p>
        </div>
        <button
          onClick={handleSave}
          disabled={saving}
          className="bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium px-4 py-2 rounded-lg transition disabled:opacity-50"
        >
          {saving ? "Saving..." : "Save Changes"}
        </button>
      </div>

      {/* Confidence Thresholds */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6 mb-6">
        <h2 className="text-base font-semibold text-gray-900 mb-1">
          Confidence Thresholds
        </h2>
        <p className="text-xs text-gray-500 mb-4">
          Minimum confidence required before the waterfall advances to the next source.
        </p>
        <SliderField
          label="FAQ Similarity Threshold"
          description="Bedrock KB cosine similarity score (default: 0.75)"
          value={parseFloat(String(form.faq_threshold ?? 0.75))}
          min={0.25}
          max={1.0}
          step={0.05}
          onChange={(v) => setForm((f) => ({ ...f, faq_threshold: String(v) }))}
        />
        <SliderField
          label="Discord Overlap Threshold"
          description="Keyword match percentage for Discord search (default: 0.70)"
          value={parseFloat(String(form.discord_threshold ?? 0.7))}
          min={0.25}
          max={1.0}
          step={0.05}
          onChange={(v) => setForm((f) => ({ ...f, discord_threshold: String(v) }))}
        />
        <SliderField
          label="Query Expansion Depth"
          description="Number of keywords generated by Nova Pro (7–15)"
          value={form.query_expansion_depth ?? 10}
          min={7}
          max={15}
          step={1}
          onChange={(v) => setForm((f) => ({ ...f, query_expansion_depth: v }))}
        />
        <SliderField
          label="Max Queries per User per Hour"
          description="Rate limit for Discord users (default: 20)"
          value={form.max_queries_per_hour ?? 20}
          min={1}
          max={100}
          step={1}
          onChange={(v) => setForm((f) => ({ ...f, max_queries_per_hour: v }))}
        />
      </div>

      {/* Agent Toggles */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
        <h2 className="text-base font-semibold text-gray-900 mb-1">
          Agent Toggles
        </h2>
        <p className="text-xs text-gray-500 mb-4">
          Enable or disable individual agents in the waterfall.
        </p>
        <Toggle
          label="FAQ Agent"
          description="Semantic search against Bedrock Knowledge Base (always recommended)"
          checked={form.enable_faq_agent ?? true}
          onChange={(v) => setForm((f) => ({ ...f, enable_faq_agent: v }))}
        />
        <Toggle
          label="Discord History Agent"
          description="Search past Discord channel discussions with query expansion"
          checked={form.enable_discord_agent ?? true}
          onChange={(v) => setForm((f) => ({ ...f, enable_discord_agent: v }))}
        />
        <Toggle
          label="Reasoning Agent"
          description="Claude Sonnet synthesis (most expensive — ~$0.05/query)"
          checked={form.enable_reasoning_agent ?? true}
          onChange={(v) => setForm((f) => ({ ...f, enable_reasoning_agent: v }))}
        />
        <Toggle
          label="AWS Documentation Agent"
          description="Claude Sonnet with AWS documentation context"
          checked={form.enable_aws_docs_agent ?? true}
          onChange={(v) => setForm((f) => ({ ...f, enable_aws_docs_agent: v }))}
        />
        <Toggle
          label="Online Search Agent"
          description="Web search fallback (optional, disabled by default)"
          checked={form.enable_online_search_agent ?? false}
          onChange={(v) => setForm((f) => ({ ...f, enable_online_search_agent: v }))}
        />
      </div>
    </div>
  );
}
