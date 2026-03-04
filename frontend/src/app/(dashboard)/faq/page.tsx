"use client";

import { useState, useCallback } from "react";
import { useDropzone } from "react-dropzone";
import useSWR from "swr";
import toast from "react-hot-toast";
import api from "@/lib/api";
import type { FAQEntry, FAQSyncStatus } from "@/types";
import { Upload, RefreshCw, Download, FileText } from "lucide-react";

const STATUS_COLORS: Record<FAQSyncStatus["status"], string> = {
  COMPLETED: "bg-green-100 text-green-700 border-green-200",
  SYNCING: "bg-blue-100 text-blue-700 border-blue-200",
  PENDING: "bg-yellow-100 text-yellow-700 border-yellow-200",
  FAILED: "bg-red-100 text-red-700 border-red-200",
  NO_DATA: "bg-gray-100 text-gray-600 border-gray-200",
  ERROR: "bg-red-100 text-red-700 border-red-200",
};

function SyncStatusCard({ status }: { status: FAQSyncStatus | undefined }) {
  if (!status) return null;
  return (
    <div className={`rounded-lg border px-4 py-3 ${STATUS_COLORS[status.status]} flex items-center justify-between`}>
      <div>
        <span className="text-sm font-semibold">{status.status}</span>
        {status.entry_count > 0 && (
          <span className="text-xs ml-2">{status.entry_count} entries loaded</span>
        )}
        {status.last_updated && (
          <span className="text-xs ml-2 opacity-70">
            Last sync: {new Date(status.last_updated).toLocaleString()}
          </span>
        )}
      </div>
      {status.status === "SYNCING" && (
        <RefreshCw size={16} className="animate-spin opacity-70" />
      )}
    </div>
  );
}

export default function FAQPage() {
  const [uploading, setUploading] = useState(false);

  const { data: syncStatus, mutate: mutateStatus } = useSWR<FAQSyncStatus>(
    "faq-sync",
    () => api.faq.syncStatus(),
    { refreshInterval: 5000 }
  );

  const { data: entries, mutate: mutateEntries } = useSWR<{
    entries: FAQEntry[];
    total: number;
  }>("faq-entries", () => api.faq.entries());

  const onDrop = useCallback(
    async (acceptedFiles: File[]) => {
      const file = acceptedFiles[0];
      if (!file) return;

      const ext = file.name.split(".").pop()?.toLowerCase() ?? "json";
      if (!["csv", "json", "md"].includes(ext)) {
        toast.error("Only CSV, JSON, and Markdown (.md) files are supported");
        return;
      }

      setUploading(true);
      const toastId = toast.loading(`Uploading ${file.name}...`);

      try {
        const content = await file.arrayBuffer();
        const result = await api.faq.upload(content, ext);
        toast.dismiss(toastId);
        toast.success(
          `Uploaded ${result.entry_count} entries. Syncing to Knowledge Base...`
        );
        mutateStatus();
        mutateEntries();
      } catch (err: unknown) {
        toast.dismiss(toastId);
        toast.error(
          err instanceof Error ? err.message : "Upload failed"
        );
      } finally {
        setUploading(false);
      }
    },
    [mutateStatus, mutateEntries]
  );

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      "text/csv": [".csv"],
      "application/json": [".json"],
      "text/markdown": [".md"],
    },
    maxFiles: 1,
    disabled: uploading,
  });

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">FAQ Management</h1>
        <p className="text-sm text-gray-500 mt-1">
          Upload FAQ files to the knowledge base. Supported formats: CSV, JSON, Markdown.
        </p>
      </div>

      {/* Sync Status */}
      <div className="mb-6">
        <SyncStatusCard status={syncStatus} />
      </div>

      {/* Upload Zone */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6 mb-6">
        <h2 className="text-base font-semibold text-gray-900 mb-4">Upload FAQ File</h2>
        <div
          {...getRootProps()}
          className={`border-2 border-dashed rounded-xl p-10 text-center cursor-pointer transition ${
            isDragActive
              ? "border-blue-500 bg-blue-50"
              : uploading
              ? "border-gray-200 bg-gray-50 cursor-not-allowed"
              : "border-gray-300 hover:border-blue-400 hover:bg-blue-50"
          }`}
        >
          <input {...getInputProps()} />
          <Upload
            size={36}
            className={`mx-auto mb-3 ${isDragActive ? "text-blue-500" : "text-gray-400"}`}
          />
          {uploading ? (
            <p className="text-sm text-gray-500">Uploading...</p>
          ) : isDragActive ? (
            <p className="text-sm text-blue-600 font-medium">Drop to upload</p>
          ) : (
            <>
              <p className="text-sm font-medium text-gray-700">
                Drag & drop your FAQ file here
              </p>
              <p className="text-xs text-gray-500 mt-1">
                or <span className="text-blue-600 underline">browse files</span>
              </p>
              <p className="text-xs text-gray-400 mt-2">CSV, JSON, or Markdown · Max 10MB</p>
            </>
          )}
        </div>

        <div className="mt-4 bg-gray-50 rounded-lg p-4 text-xs text-gray-600">
          <p className="font-medium text-gray-700 mb-1">Expected file formats:</p>
          <p>
            <strong>CSV</strong>: columns — id, question, answer, category, tags (semicolon-separated)
          </p>
          <p className="mt-1">
            <strong>JSON</strong>: array of{" "}
            {"{ id, question, answer, category, tags[] }"}
          </p>
          <p className="mt-1">
            <strong>Markdown</strong>: sections starting with{" "}
            <code>## Q: Question text</code>, followed by <code>A: Answer</code>
          </p>
        </div>
      </div>

      {/* FAQ Entries Table */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-base font-semibold text-gray-900">
            Current FAQ Entries ({entries?.total ?? 0})
          </h2>
          <button
            onClick={() => mutateEntries()}
            className="flex items-center gap-2 text-sm text-gray-500 hover:text-gray-900 transition"
          >
            <RefreshCw size={14} />
            Refresh
          </button>
        </div>

        {entries?.entries && entries.entries.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100">
                  <th className="text-left py-2 px-3 text-xs font-medium text-gray-500 uppercase tracking-wide">ID</th>
                  <th className="text-left py-2 px-3 text-xs font-medium text-gray-500 uppercase tracking-wide">File</th>
                  <th className="text-left py-2 px-3 text-xs font-medium text-gray-500 uppercase tracking-wide">Size</th>
                  <th className="text-left py-2 px-3 text-xs font-medium text-gray-500 uppercase tracking-wide">Last Modified</th>
                </tr>
              </thead>
              <tbody>
                {entries.entries.map((entry) => (
                  <tr key={entry.id} className="border-b border-gray-50 hover:bg-gray-50">
                    <td className="py-2 px-3 font-mono text-xs text-gray-700">{entry.id}</td>
                    <td className="py-2 px-3">
                      <div className="flex items-center gap-2">
                        <FileText size={14} className="text-gray-400" />
                        <span className="text-gray-700">{entry.s3_key.split("/").pop()}</span>
                      </div>
                    </td>
                    <td className="py-2 px-3 text-gray-500 text-xs">{entry.size}B</td>
                    <td className="py-2 px-3 text-gray-500 text-xs">
                      {new Date(entry.last_modified).toLocaleDateString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="py-12 text-center text-gray-400 text-sm">
            No FAQ entries uploaded yet. Upload a file above to get started.
          </div>
        )}
      </div>
    </div>
  );
}
