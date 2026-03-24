import type { Metadata } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans } from "next/font/google";
import "./globals.css";
import { ModeProvider } from "./providers";

const ibmMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
  style: ["normal", "italic"],
  variable: "--font-ibm-mono",
  display: "swap",
});

const ibmSans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600"],
  variable: "--font-ibm-sans",
  display: "swap",
});

export const metadata: Metadata = {
  title: "norma.ai — Agent Governance",
  description: "The operating system for your AI agents",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${ibmMono.variable} ${ibmSans.variable}`}>
      <body>
        <ModeProvider>{children}</ModeProvider>
      </body>
    </html>
  );
}
