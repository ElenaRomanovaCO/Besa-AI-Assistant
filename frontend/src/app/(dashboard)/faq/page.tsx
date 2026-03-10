"use client";

import { useState, useCallback } from "react";
import { useDropzone } from "react-dropzone";
import useSWR from "swr";
import toast from "react-hot-toast";
import api from "@/lib/api";
import type { FAQFile, FAQSyncStatus } from "@/types";
import { Upload, RefreshCw, FileText, Trash2, AlertTriangle } from "lucide-react";

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

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function FAQPage() {
  const [uploading, setUploading] = useState(false);
  const [deletingFile, setDeletingFile] = useState<string | null>(null);
  // Pending duplicate: holds file + content waiting for user confirmation
  const [pendingUpload, setPendingUpload] = useState<{
    file: File;
    content: string;
  } | null>(null);

  const { data: syncStatus, mutate: mutateStatus } = useSWR<FAQSyncStatus>(
    "faq-sync",
    () => api.faq.syncStatus(),
    { refreshInterval: 5000 }
  );

  const { data: filesData, mutate: mutateFiles } = useSWR<{
    files: FAQFile[];
    total: number;
  }>("faq-files", () => api.faq.files());

  const doUpload = useCallback(
    async (file: File, content: string, overwrite = false) => {
      setUploading(true);
      const toastId = toast.loading(`Uploading ${file.name}...`);
      try {
        const result = await api.faq.upload(content, file.name, overwrite);
        toast.dismiss(toastId);
        if (result.ok) {
          toast.success(`${file.name} uploaded. Syncing to Knowledge Base...`);
          setPendingUpload(null);
          mutateStatus();
          mutateFiles();
        } else if (result.status === 409) {
          // File exists — show confirmation dialog
          toast.dismiss(toastId);
          setPendingUpload({ file, content });
        } else {
          const msg = (result.data as { error?: string })?.error ?? "Upload failed";
          toast.error(msg);
        }
      } catch (err: unknown) {
        toast.dismiss(toastId);
        toast.error(err instanceof Error ? err.message : "Upload failed");
      } finally {
        setUploading(false);
      }
    },
    [mutateStatus, mutateFiles]
  );

  const onDrop = useCallback(
    async (acceptedFiles: File[]) => {
      const file = acceptedFiles[0];
      if (!file) return;
      const content = await file.text();
      await doUpload(file, content, false);
    },
    [doUpload]
  );

  const handleConfirmReplace = useCallback(async () => {
    if (!pendingUpload) return;
    await doUpload(pendingUpload.file, pendingUpload.content, true);
  }, [pendingUpload, doUpload]);

  const handleDelete = useCallback(
    async (filename: string) => {
      if (!confirm(`Delete "${filename}" from the knowledge base?`)) return;
      setDeletingFile(filename);
      try {
        await api.faq.deleteFile(filename);
        toast.success(`${filename} deleted. Re-syncing Knowledge Base...`);
        mutateStatus();
        mutateFiles();
      } catch (err: unknown) {
        toast.error(err instanceof Error ? err.message : "Delete failed");
      } finally {
        setDeletingFile(null);
      }
    },
    [mutateStatus, mutateFiles]
  );

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { "text/markdown": [".md"], "text/plain": [".md", ".txt"] },
    maxFiles: 1,
    disabled: uploading,
  });

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">FAQ Management</h1>
        <p className="text-sm text-gray-500 mt-1">
          Upload Markdown files to the knowledge base. Bedrock handles chunking automatically.
        </p>
      </div>

      {/* Sync Status */}
      <div className="mb-6">
        <SyncStatusCard status={syncStatus} />
      </div>

      {/* Duplicate confirmation dialog */}
      {pendingUpload && (
        <div className="mb-6 rounded-xl border border-yellow-300 bg-yellow-50 p-5">
          <div className="flex items-start gap-3">
            <AlertTriangle size={20} className="text-yellow-600 mt-0.5 shrink-0" />
            <div className="flex-1">
              <p className="text-sm font-semibold text-yellow-800">
                {pendingUpload.file.name} already exists
              </p>
              <p className="text-xs text-yellow-700 mt-1">
                Do you want to replace the existing file in the knowledge base?
              </p>
              <div className="flex gap-2 mt-3">
                <button
                  onClick={handleConfirmReplace}
                  disabled={uploading}
                  className="px-3 py-1.5 text-xs font-medium bg-yellow-600 text-white rounded-lg hover:bg-yellow-700 disabled:opacity-50"
                >
                  Replace
                </button>
                <button
                  onClick={() => setPendingUpload(null)}
                  className="px-3 py-1.5 text-xs font-medium text-gray-600 border border-gray-300 rounded-lg hover:bg-gray-50"
                >
                  Cancel
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

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
                Drag & drop a Markdown file here
              </p>
              <p className="text-xs text-gray-500 mt-1">
                or <span className="text-blue-600 underline">browse files</span>
              </p>
              <p className="text-xs text-gray-400 mt-2">
                Any .md format · Max 10 MB · Multiple files supported
              </p>
            </>
          )}
        </div>
      </div>

      {/* Uploaded Files Table */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-base font-semibold text-gray-900">
            Knowledge Base Files ({filesData?.total ?? 0})
          </h2>
          <button
            onClick={() => mutateFiles()}
            className="flex items-center gap-2 text-sm text-gray-500 hover:text-gray-900 transition"
          >
            <RefreshCw size={14} />
            Refresh
          </button>
        </div>

        {filesData?.files && filesData.files.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100">
                  <th className="text-left py-2 px-3 text-xs font-medium text-gray-500 uppercase tracking-wide">File</th>
                  <th className="text-left py-2 px-3 text-xs font-medium text-gray-500 uppercase tracking-wide">Size</th>
                  <th className="text-left py-2 px-3 text-xs font-medium text-gray-500 uppercase tracking-wide">Uploaded</th>
                  <th className="text-left py-2 px-3 text-xs font-medium text-gray-500 uppercase tracking-wide">By</th>
                  <th className="py-2 px-3"></th>
                </tr>
              </thead>
              <tbody>
                {filesData.files.map((file) => (
                  <tr key={file.filename} className="border-b border-gray-50 hover:bg-gray-50">
                    <td className="py-2 px-3">
                      <div className="flex items-center gap-2">
                        <FileText size={14} className="text-gray-400 shrink-0" />
                        <span className="font-medium text-gray-800">{file.filename}</span>
                      </div>
                    </td>
                    <td className="py-2 px-3 text-gray-500 text-xs">{formatBytes(file.size)}</td>
                    <td className="py-2 px-3 text-gray-500 text-xs">
                      {new Date(file.last_modified).toLocaleString()}
                    </td>
                    <td className="py-2 px-3 text-gray-500 text-xs">{file.uploaded_by || "—"}</td>
                    <td className="py-2 px-3 text-right">
                      <button
                        onClick={() => handleDelete(file.filename)}
                        disabled={deletingFile === file.filename}
                        className="p-1.5 text-gray-400 hover:text-red-500 rounded transition disabled:opacity-40"
                        title="Delete file"
                      >
                        {deletingFile === file.filename ? (
                          <RefreshCw size={14} className="animate-spin" />
                        ) : (
                          <Trash2 size={14} />
                        )}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="py-12 text-center text-gray-400 text-sm">
            No files uploaded yet. Drop a Markdown file above to get started.
          </div>
        )}
      </div>
    </div>
  );
}
