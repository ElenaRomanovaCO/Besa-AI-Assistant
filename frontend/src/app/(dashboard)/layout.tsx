"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { usePathname } from "next/navigation";
import toast from "react-hot-toast";
import { getAuthenticatedUser, logout } from "@/lib/auth";
import {
  LayoutDashboard,
  Settings,
  BookOpen,
  Hash,
  ScrollText,
  BarChart3,
  LogOut,
  Menu,
  X,
} from "lucide-react";

const navItems = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/configuration", label: "Configuration", icon: Settings },
  { href: "/faq", label: "FAQ Management", icon: BookOpen },
  { href: "/channels", label: "Channels", icon: Hash },
  { href: "/logs", label: "Query Logs", icon: ScrollText },
  { href: "/analytics", label: "Analytics", icon: BarChart3 },
];

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const [userEmail, setUserEmail] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(false);

  useEffect(() => {
    getAuthenticatedUser().then((user) => {
      if (!user) {
        router.replace("/login");
        return;
      }
      setUserEmail(user.username || user.userId || "");
    });
  }, [router]);

  async function handleLogout() {
    await logout();
    toast.success("Signed out");
    router.replace("/login");
  }

  const Sidebar = () => (
    <div className="flex flex-col h-full">
      {/* Logo */}
      <div className="px-6 py-5 border-b border-gray-700">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 bg-aws-orange rounded-lg flex items-center justify-center text-sm">
            🤖
          </div>
          <div>
            <p className="text-white font-semibold text-sm">BeSa AI Admin</p>
            <p className="text-gray-400 text-xs">AWS Workshop Assistant</p>
          </div>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 py-4 space-y-1">
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = pathname === item.href || pathname.startsWith(item.href + "/");
          return (
            <Link
              key={item.href}
              href={item.href}
              onClick={() => setSidebarOpen(false)}
              className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition ${
                isActive
                  ? "bg-aws-orange text-white font-medium"
                  : "text-gray-300 hover:bg-gray-700 hover:text-white"
              }`}
            >
              <Icon size={18} />
              {item.label}
            </Link>
          );
        })}
      </nav>

      {/* User footer */}
      <div className="px-3 py-4 border-t border-gray-700">
        <div className="px-3 py-2 mb-1">
          <p className="text-xs text-gray-400">Signed in as</p>
          <p className="text-sm text-gray-200 truncate">{userEmail}</p>
        </div>
        <button
          onClick={handleLogout}
          className="flex items-center gap-3 w-full px-3 py-2 rounded-lg text-sm text-gray-300 hover:bg-gray-700 hover:text-white transition"
        >
          <LogOut size={18} />
          Sign out
        </button>
      </div>
    </div>
  );

  return (
    <div className="flex h-screen bg-gray-50">
      {/* Desktop sidebar */}
      <aside className="hidden lg:flex lg:flex-col w-64 bg-aws-squid-ink flex-shrink-0">
        <Sidebar />
      </aside>

      {/* Mobile sidebar overlay */}
      {sidebarOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div
            className="absolute inset-0 bg-black/50"
            onClick={() => setSidebarOpen(false)}
          />
          <aside className="relative flex flex-col w-64 h-full bg-aws-squid-ink">
            <button
              onClick={() => setSidebarOpen(false)}
              className="absolute top-4 right-4 text-gray-400 hover:text-white"
            >
              <X size={20} />
            </button>
            <Sidebar />
          </aside>
        </div>
      )}

      {/* Main content */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Mobile header */}
        <header className="lg:hidden flex items-center gap-4 px-4 py-3 bg-white border-b">
          <button
            onClick={() => setSidebarOpen(true)}
            className="text-gray-600 hover:text-gray-900"
          >
            <Menu size={20} />
          </button>
          <span className="font-semibold text-gray-900">BeSa AI Admin</span>
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-y-auto">{children}</main>
      </div>
    </div>
  );
}
