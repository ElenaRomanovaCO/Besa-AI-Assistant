"use client";

import { useState, useEffect } from "react";
import useSWR from "swr";
import toast from "react-hot-toast";
import api from "@/lib/api";
import type { DiscordChannel, SystemConfig } from "@/types";
import { Hash, CheckCircle2, Circle } from "lucide-react";

export default function ChannelsPage() {
  const { data: channelData, isLoading } = useSWR<{ channels: DiscordChannel[] }>(
    "channels",
    () => api.discord.channels()
  );

  const { data: config } = useSWR<SystemConfig>("config", () => api.config.get());

  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (config?.searchable_channel_ids) {
      setSelected(new Set(config.searchable_channel_ids));
    }
  }, [config]);

  function toggleChannel(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }

  async function handleSave() {
    setSaving(true);
    try {
      await api.config.update({ searchable_channel_ids: Array.from(selected) });
      toast.success(`${selected.size} channel(s) configured for Discord search`);
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  const channels = channelData?.channels ?? [];

  return (
    <div className="p-6 max-w-3xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Discord Channels</h1>
          <p className="text-sm text-gray-500 mt-1">
            Select which channels the Discord History Agent will search. {selected.size} selected.
          </p>
        </div>
        <button
          onClick={handleSave}
          disabled={saving}
          className="bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium px-4 py-2 rounded-lg transition disabled:opacity-50"
        >
          {saving ? "Saving..." : "Save Selection"}
        </button>
      </div>

      <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
        {isLoading ? (
          <div className="flex items-center justify-center h-48 text-gray-400">
            <div className="animate-spin h-5 w-5 border-2 border-blue-600 border-t-transparent rounded-full" />
          </div>
        ) : channels.length === 0 ? (
          <div className="py-12 text-center text-gray-400 text-sm">
            <p>No channels found.</p>
            <p className="mt-1 text-xs">
              Make sure the Discord bot has access to your server and DISCORD_GUILD_ID is configured.
            </p>
          </div>
        ) : (
          <div className="divide-y divide-gray-50">
            {channels.map((ch: DiscordChannel) => {
              const isSelected = selected.has(ch.channel_id);
              return (
                <button
                  key={ch.channel_id}
                  onClick={() => toggleChannel(ch.channel_id)}
                  className="w-full flex items-center gap-4 px-5 py-4 hover:bg-gray-50 transition text-left"
                >
                  <div className={`flex-shrink-0 ${isSelected ? "text-blue-600" : "text-gray-300"}`}>
                    {isSelected ? <CheckCircle2 size={20} /> : <Circle size={20} />}
                  </div>
                  <Hash size={16} className="text-gray-400 flex-shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-900">{ch.name}</p>
                    {ch.topic && (
                      <p className="text-xs text-gray-500 truncate mt-0.5">{ch.topic}</p>
                    )}
                  </div>
                  <span className="text-xs text-gray-400 flex-shrink-0">{ch.channel_id}</span>
                </button>
              );
            })}
          </div>
        )}
      </div>

      {selected.size > 0 && (
        <div className="mt-4 bg-blue-50 rounded-lg p-4 text-sm text-blue-700">
          <strong>{selected.size} channel(s) selected</strong> will be searched when a student
          asks a question that doesn't match the FAQ with high confidence.
        </div>
      )}
    </div>
  );
}
