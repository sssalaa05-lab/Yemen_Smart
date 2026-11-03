import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";
import { Toaster } from "@/components/ui/toaster";

// IBM Plex Sans Arabic — خط الطرفية المالي الاحترافي (RTL أصلي)
const plexArabic = localFont({
  src: [
    { path: "../fonts/IBMPlexSansArabic-Regular.ttf", weight: "400", style: "normal" },
    { path: "../fonts/IBMPlexSansArabic-Medium.ttf", weight: "500", style: "normal" },
    { path: "../fonts/IBMPlexSansArabic-SemiBold.ttf", weight: "600", style: "normal" },
    { path: "../fonts/IBMPlexSansArabic-Bold.ttf", weight: "700", style: "normal" },
  ],
  variable: "--font-plex-arabic",
  display: "swap",
});

// IBM Plex Mono — للأرقام والأسعار (tabular alignment)
const plexMono = localFont({
  src: [
    { path: "../fonts/IBMPlexMono-Regular.ttf", weight: "400", style: "normal" },
    { path: "../fonts/IBMPlexMono-Medium.ttf", weight: "500", style: "normal" },
    { path: "../fonts/IBMPlexMono-SemiBold.ttf", weight: "600", style: "normal" },
  ],
  variable: "--font-plex-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "FinGPT Gold — طرفية سوق الذهب الذكية",
  description:
    "طرفية تحليل مشاعر سوق الذهب: نموذج FinGPT مُخصص لأخبار الذهب (دقة 92.5%)، رسم TradingView حي، جدول AG Grid، وأسعار COMEX حقيقية.",
  icons: {
    icon: "https://z-cdn.chatglm.cn/z-ai/static/logo.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ar" dir="rtl" className="dark" suppressHydrationWarning>
      <body
        className={`${plexArabic.variable} ${plexMono.variable} antialiased bg-background text-foreground`}
      >
        {children}
        <Toaster />
      </body>
    </html>
  );
}
