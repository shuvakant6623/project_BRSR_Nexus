import { AppShellNav } from "@/components/AppShellNav";
import { AuthProvider } from "@/components/AuthProvider";
import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "BRSR Reporting Portal",
  description: "Metadata-driven BRSR data management and reporting platform",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <AuthProvider>
          <AppShellNav />
          {children}
        </AuthProvider>
      </body>
    </html>
  );
}
