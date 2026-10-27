// gen_guide.js — assembles Nexus Setup & Operations Guide (Arabic RTL)
const {
  Document, Packer, Paragraph, TextRun, Header, Footer, PageNumber,
  AlignmentType, NumberFormat, SectionType, TableOfContents, PageOrientation,
} = require("docx");
const fs = require("fs");
const { PAL, AR_FONT, ar, buildCoverR1RTL } = require("./guide_lib");
const c1 = require("./guide_content");
const c2 = require("./guide_content2");

const pgSize = { width: 11906, height: 16838, orientation: PageOrientation.PORTRAIT };
const pgMargin = { top: 1440, bottom: 1440, left: 1701, right: 1417 };

// ---------- cover ----------
const coverConfig = {
  title: "دليل التشغيل والتركيب",
  subtitle: "نظام Nexus للتداول الآلي عبر MetaTrader 5",
  englishLabel: "NEXUS TRADING SYSTEM",
  metaLines: [
    "الإصدار: أكتوبر 2026 — يشمل ميزات التقويم الاقتصادي (47 ميزة)",
    "الأرشيف المرجعي: nexus-backup-2026-10-27.tar.gz",
    "المنصات: خادم Linux + جهاز Windows مع MetaTrader 5",
  ],
  footerLeft: "Nexus Trading System MT5",
  footerRight: "أكتوبر 2026",
  palette: { bg: PAL.bg, accent: PAL.accent, cover: PAL.cover },
};

// ---------- footers / header ----------
function pageNumFooter() {
  return new Footer({
    children: [new Paragraph({
      alignment: AlignmentType.CENTER,
      children: [new TextRun({ children: [PageNumber.CURRENT], size: 18, color: "6A7480", font: AR_FONT })],
    })],
  });
}

function bodyHeader() {
  return new Header({
    children: [new Paragraph({
      bidirectional: true, alignment: AlignmentType.CENTER,
      border: { bottom: { style: "single", size: 2, color: PAL.table.innerLine, space: 4 } },
      children: [ar("دليل التشغيل والتركيب — نظام Nexus للتداول الآلي", { size: 16, color: "8A94A0" })],
    })],
  });
}

// ---------- front matter (TOC) ----------
const frontMatter = [
  new Paragraph({
    bidirectional: true, alignment: AlignmentType.CENTER,
    spacing: { before: 480, after: 360, line: 400, lineRule: "atLeast" },
    children: [ar("المحتويات", { bold: true, size: 32, color: PAL.h1 })],
  }),
  new TableOfContents("Table of Contents", { hyperlink: true, headingStyleRange: "1-2" }),
  new Paragraph({
    bidirectional: true, alignment: AlignmentType.RIGHT,
    spacing: { before: 200, line: 312 },
    children: [ar("ملاحظة: هذا الفهرس مولد بحقول آلية؛ بعد أي تعديل في الوثيقة انقر بزر الفأرة الأيمن على الفهرس واختر تحديث الحقل لضبط أرقام الصفحات.", { italics: true, size: 18, color: "888888" })],
  }),
];

// ---------- body ----------
const body = [
  ...c1.section1(), ...c1.section2(), ...c1.section3(), ...c1.section4(), ...c1.section5(),
  ...c2.section6(), ...c2.section7(), ...c2.section8(), ...c2.section9(), ...c2.section10(),
];

const doc = new Document({
  features: { updateFields: true },
  styles: {
    default: {
      document: {
        run: { font: AR_FONT, size: 24, color: PAL.body },
        paragraph: { spacing: { line: 312 } },
      },
      heading1: {
        run: { font: AR_FONT, size: 32, bold: true, color: PAL.h1 },
        paragraph: { spacing: { before: 400, after: 160 }, outlineLevel: 0 },
      },
      heading2: {
        run: { font: AR_FONT, size: 28, bold: true, color: PAL.h2 },
        paragraph: { spacing: { before: 260, after: 120 }, outlineLevel: 1 },
      },
    },
  },
  sections: [
    { // Section 1: cover — margin 0, no footer, no pageNumbers
      properties: { page: { size: pgSize, margin: { top: 0, bottom: 0, left: 0, right: 0 } } },
      children: buildCoverR1RTL(coverConfig),
    },
    { // Section 2: front matter (TOC) — Roman numerals
      properties: {
        type: SectionType.NEXT_PAGE,
        page: { size: pgSize, margin: pgMargin, pageNumbers: { start: 1, formatType: NumberFormat.UPPER_ROMAN } },
      },
      footers: { default: pageNumFooter() },
      children: frontMatter,
    },
    { // Section 3: body — Arabic numerals reset to 1
      properties: {
        type: SectionType.NEXT_PAGE,
        page: { size: pgSize, margin: pgMargin, pageNumbers: { start: 1, formatType: NumberFormat.DECIMAL } },
      },
      headers: { default: bodyHeader() },
      footers: { default: pageNumFooter() },
      children: body,
    },
  ],
});

const OUT = "/home/z/my-project/download/Nexus-Setup-Guide-AR.docx";
Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync(OUT, buf);
  console.log("WROTE", OUT, buf.length, "bytes");
});
