"use client";

// 🥇 يمن سمارت — غلاف المسار المستقل يستخدم نفس مكوّن اللوحة المضمّن في الرئيسية
import YemenSmartPanel from "@/components/gold/YemenSmartPanel";

export default function YemenSmartGoldPage() {
  return <YemenSmartPanel onBack={() => { window.location.href = "/" }} />;
}
