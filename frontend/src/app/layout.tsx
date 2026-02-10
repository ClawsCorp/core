import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "ClawsCorp Portal",
  description: "Read-only public portal for ClawsCorp Core.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
