"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";

import { useAuth } from "@/components/AuthProvider";

const NAV: Record<string, { href: string; label: string }[]> = {
  ADMIN: [
    { href: "/", label: "Overview" },
    { href: "/entities", label: "Entities" },
    { href: "/framework", label: "Framework" },
  ],
  ESG_MANAGER: [
    { href: "/", label: "Overview" },
    { href: "/entities", label: "Entities" },
    { href: "/framework", label: "Framework" },
  ],
  MANAGEMENT: [
    { href: "/", label: "Dashboard" },
    { href: "/framework", label: "Framework" },
  ],
  REVIEWER: [
    { href: "/", label: "Overview" },
    { href: "/framework", label: "Framework" },
  ],
  ASSESSOR: [
    { href: "/", label: "Overview" },
    { href: "/framework", label: "Framework" },
  ],
  DATA_OWNER: [
    { href: "/", label: "My Dashboard" },
    { href: "/framework", label: "Framework" },
  ],
};

export function AppShellNav() {
  const { user, loading, logout } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (!loading && !user && pathname !== "/login") router.push("/login");
  }, [loading, user, pathname, router]);

  if (loading || !user) return null;
  const items = NAV[user.role] ?? [];

  return (
    <header className="topbar">
      <span className="brand">BRSR Reporting Portal</span>
      <nav className="nav">
        {items.map((i) => (
          <Link key={i.href} href={i.href} className={pathname === i.href ? "active" : ""}>
            {i.label}
          </Link>
        ))}
      </nav>
      <span className="userchip">
        {user.full_name} · {user.role.replace("_", " ")}
      </span>
      <button className="ghostbtn" onClick={() => logout().then(() => router.push("/login"))}>
        Sign out
      </button>
    </header>
  );
}
