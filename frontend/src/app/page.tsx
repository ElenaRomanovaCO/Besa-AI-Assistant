"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { getAuthenticatedUser } from "@/lib/auth";

export default function RootPage() {
  const router = useRouter();

  useEffect(() => {
    getAuthenticatedUser().then((user) => {
      if (user) {
        router.replace("/dashboard");
      } else {
        router.replace("/login");
      }
    });
  }, [router]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="flex items-center gap-3 text-gray-500">
        <svg className="animate-spin h-5 w-5" viewBox="0 0 24 24" fill="none">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
        <span>Loading BeSa AI Admin...</span>
      </div>
    </div>
  );
}
