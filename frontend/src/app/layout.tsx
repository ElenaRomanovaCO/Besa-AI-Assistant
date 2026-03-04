"use client";

import "./globals.css";
import { Toaster } from "react-hot-toast";
import { configureAmplify } from "@/lib/auth";

// Configure Amplify immediately at module load time so all SWR hooks
// that fire on first render already have a configured Amplify instance.
configureAmplify();

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <title>BeSa AI Assistant — Admin</title>
        <meta name="description" content="Admin interface for BeSa AWS Workshop AI Assistant" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>
        <>
          {children}
          <Toaster
            position="top-right"
            toastOptions={{
              duration: 4000,
              style: {
                background: "#1f2937",
                color: "#f9fafb",
                borderRadius: "8px",
              },
              success: { iconTheme: { primary: "#10b981", secondary: "#f9fafb" } },
              error: { iconTheme: { primary: "#ef4444", secondary: "#f9fafb" } },
            }}
          />
        </>
      </body>
    </html>
  );
}
