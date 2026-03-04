"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import toast from "react-hot-toast";
import { login } from "@/lib/auth";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [newPassword, setNewPassword] = useState("");
  const [requiresNewPassword, setRequiresNewPassword] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);

    try {
      const result = await login(email, password);

      if (result.nextStep?.signInStep === "CONFIRM_SIGN_IN_WITH_NEW_PASSWORD_REQUIRED") {
        setRequiresNewPassword(true);
        setLoading(false);
        return;
      }

      if (result.isSignedIn) {
        toast.success("Signed in successfully");
        router.replace("/dashboard");
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Login failed";
      toast.error(message);
      setLoading(false);
    }
  }

  async function handleNewPassword(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    try {
      const { confirmSignIn } = await import("aws-amplify/auth");
      const result = await confirmSignIn({ challengeResponse: newPassword });
      if (result.isSignedIn) {
        toast.success("Password updated. Signed in successfully.");
        router.replace("/dashboard");
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Failed to set new password";
      toast.error(message);
      setLoading(false);
    }
  }

  if (requiresNewPassword) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 px-4">
        <div className="w-full max-w-md">
          <div className="bg-white rounded-xl shadow-lg p-8">
            <h2 className="text-2xl font-bold text-gray-900 mb-2">Set New Password</h2>
            <p className="text-gray-500 text-sm mb-6">
              Your temporary password has expired. Please set a new password.
            </p>
            <form onSubmit={handleNewPassword} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  New Password
                </label>
                <input
                  type="password"
                  required
                  minLength={12}
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="Min. 12 characters with upper, lower, digits, symbols"
                />
              </div>
              <button
                type="submit"
                disabled={loading}
                className="w-full bg-blue-600 hover:bg-blue-700 text-white font-medium py-2 px-4 rounded-lg transition disabled:opacity-50"
              >
                {loading ? "Saving..." : "Set Password & Sign In"}
              </button>
            </form>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 px-4">
      <div className="w-full max-w-md">
        {/* Header */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 bg-aws-squid-ink rounded-2xl mb-4">
            <span className="text-2xl">🤖</span>
          </div>
          <h1 className="text-3xl font-bold text-gray-900">BeSa AI Admin</h1>
          <p className="text-gray-500 mt-2">AWS Workshop AI Assistant</p>
        </div>

        {/* Login card */}
        <div className="bg-white rounded-xl shadow-lg p-8">
          <h2 className="text-xl font-semibold text-gray-900 mb-6">Sign in to continue</h2>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Email address
              </label>
              <input
                type="email"
                required
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="you@example.com"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Password
              </label>
              <input
                type="password"
                required
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <button
              type="submit"
              disabled={loading}
              className="w-full bg-aws-squid-ink hover:bg-gray-700 text-white font-medium py-2 px-4 rounded-lg transition disabled:opacity-50 mt-2"
            >
              {loading ? "Signing in..." : "Sign in"}
            </button>
          </form>
        </div>

        <p className="text-center text-gray-400 text-xs mt-6">
          Contact your administrator if you need access.
        </p>
      </div>
    </div>
  );
}
