import "./globals.css";
import type { Metadata } from "next";
import { ReactNode } from "react";
import Providers from "../components/Providers";

export const metadata: Metadata = {
  title: "RAG Assistant",
  description: "Document grounded assistant",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-gradient-to-br from-slate-950 via-slate-900 to-indigo-950 text-white min-h-screen">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
