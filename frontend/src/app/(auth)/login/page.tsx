"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import toast from "react-hot-toast";
import { login } from "@/lib/auth";

type LoginStep = "credentials" | "new-password" | "mfa-setup" | "mfa-verify";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [newPassword, setNewPassword] = useState("");
  const [mfaCode, setMfaCode] = useState("");
  const [totpUri, setTotpUri] = useState("");
  const [step, setStep] = useState<LoginStep>("credentials");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);

    try {
      const result = await login(email, password);
      handleSignInResult(result);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Login failed";
      toast.error(message);
      setLoading(false);
    }
  }

  function handleSignInResult(result: { isSignedIn: boolean; nextStep?: { signInStep?: string } }) {
    const nextStep = result.nextStep?.signInStep;

    if (result.isSignedIn) {
      toast.success("Signed in successfully");
      router.replace("/dashboard");
      return;
    }

    if (nextStep === "CONFIRM_SIGN_IN_WITH_NEW_PASSWORD_REQUIRED") {
      setStep("new-password");
      setLoading(false);
      return;
    }

    if (nextStep === "CONTINUE_SIGN_IN_WITH_TOTP_SETUP") {
      setupTotp();
      return;
    }

    if (nextStep === "CONFIRM_SIGN_IN_WITH_TOTP_CODE") {
      setStep("mfa-verify");
      setLoading(false);
      return;
    }

    // Fallback for unknown steps
    toast.error(`Unexpected auth step: ${nextStep}`);
    setLoading(false);
  }

  async function setupTotp() {
    try {
      const { setUpTOTP } = await import("aws-amplify/auth");
      const totpSetup = await setUpTOTP();
      const uri = totpSetup.getSetupUri("BeSa AI Admin", email);
      setTotpUri(uri.toString());
      setStep("mfa-setup");
      setLoading(false);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Failed to set up MFA";
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
      handleSignInResult(result);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Failed to set new password";
      toast.error(message);
      setLoading(false);
    }
  }

  async function handleMfaVerify(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    try {
      const { confirmSignIn } = await import("aws-amplify/auth");
      const result = await confirmSignIn({ challengeResponse: mfaCode });
      handleSignInResult(result);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Invalid MFA code";
      toast.error(message);
      setLoading(false);
    }
  }

  // Extract TOTP secret from URI for manual entry
  function getTotpSecret(): string {
    try {
      const url = new URL(totpUri);
      return url.searchParams.get("secret") || "";
    } catch {
      return "";
    }
  }

  // --- New Password Step ---
  if (step === "new-password") {
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
                {loading ? "Saving..." : "Set Password & Continue"}
              </button>
            </form>
          </div>
        </div>
      </div>
    );
  }

  // --- MFA Setup Step (first time TOTP enrollment) ---
  if (step === "mfa-setup") {
    const secret = getTotpSecret();
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 px-4">
        <div className="w-full max-w-md">
          <div className="bg-white rounded-xl shadow-lg p-8">
            <h2 className="text-2xl font-bold text-gray-900 mb-2">Set Up MFA</h2>
            <p className="text-gray-500 text-sm mb-6">
              Multi-factor authentication is required. Scan the QR code below with your authenticator app
              (Google Authenticator, Authy, 1Password, etc.), then enter the 6-digit code.
            </p>

            {/* QR code via Google Charts API */}
            {totpUri && (
              <div className="flex justify-center mb-4">
                <img
                  src={`https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=${encodeURIComponent(totpUri)}`}
                  alt="TOTP QR Code"
                  width={200}
                  height={200}
                  className="rounded-lg border"
                />
              </div>
            )}

            {/* Manual secret for copy-paste */}
            {secret && (
              <div className="mb-4 p-3 bg-gray-50 rounded-lg">
                <p className="text-xs text-gray-500 mb-1">Or enter this code manually:</p>
                <code className="text-sm font-mono text-gray-800 break-all select-all">{secret}</code>
              </div>
            )}

            <form onSubmit={handleMfaVerify} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Verification Code
                </label>
                <input
                  type="text"
                  required
                  maxLength={6}
                  pattern="[0-9]{6}"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  value={mfaCode}
                  onChange={(e) => setMfaCode(e.target.value.replace(/\D/g, ""))}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-center text-lg tracking-widest focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="000000"
                />
              </div>
              <button
                type="submit"
                disabled={loading || mfaCode.length !== 6}
                className="w-full bg-blue-600 hover:bg-blue-700 text-white font-medium py-2 px-4 rounded-lg transition disabled:opacity-50"
              >
                {loading ? "Verifying..." : "Verify & Sign In"}
              </button>
            </form>
          </div>
        </div>
      </div>
    );
  }

  // --- MFA Verify Step (returning user with TOTP already set up) ---
  if (step === "mfa-verify") {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 px-4">
        <div className="w-full max-w-md">
          <div className="bg-white rounded-xl shadow-lg p-8">
            <h2 className="text-2xl font-bold text-gray-900 mb-2">Enter MFA Code</h2>
            <p className="text-gray-500 text-sm mb-6">
              Open your authenticator app and enter the 6-digit code for BeSa AI Admin.
            </p>
            <form onSubmit={handleMfaVerify} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Verification Code
                </label>
                <input
                  type="text"
                  required
                  maxLength={6}
                  pattern="[0-9]{6}"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  value={mfaCode}
                  onChange={(e) => setMfaCode(e.target.value.replace(/\D/g, ""))}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-center text-lg tracking-widest focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="000000"
                />
              </div>
              <button
                type="submit"
                disabled={loading || mfaCode.length !== 6}
                className="w-full bg-blue-600 hover:bg-blue-700 text-white font-medium py-2 px-4 rounded-lg transition disabled:opacity-50"
              >
                {loading ? "Verifying..." : "Verify & Sign In"}
              </button>
            </form>
          </div>
        </div>
      </div>
    );
  }

  // --- Credentials Step (default) ---
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
