import type { Metadata } from "next";
import { IBM_Plex_Mono, Manrope } from "next/font/google";
import { SpeedInsights } from "@vercel/speed-insights/next";

const displayFont = Manrope({
  subsets: ["latin"],
  weight: ["400", "500", "700", "800"],
  variable: "--font-display",
});

const monoFont = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-mono",
});

export const metadata: Metadata = {
  title: "ClawsCorp Portal",
  description: "Read-only public portal for ClawsCorp Core.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={monoFont.variable}>
      <body
        className={displayFont.className}
        style={{ margin: 0, background: "#111214" }}
      >
        {children}
        <SpeedInsights />
      </body>
    </html>
  );
}
