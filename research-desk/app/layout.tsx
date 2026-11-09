import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Ollie’s Research Desk",
  description: "Your private stock valuation and short-squeeze research desk.",
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  );
}
