// guide_lib.js — RTL Arabic docx helpers (docx 9.x) following docx skill design-system.md
// R1 cover recipe (mirrored for RTL) + DM-1 palette + horizontal-only business tables.
const {
  Paragraph, TextRun, Table, TableRow, TableCell, TableLayoutType,
  AlignmentType, HeadingLevel, WidthType, BorderStyle, ShadingType,
} = require("docx");

// ---------- palette (DM-1 Deep Cyan — tech/AI) ----------
const PAL = {
  bg: "162235", accent: "37DCF2",
  cover: { titleColor: "FFFFFF", subtitleColor: "B0B8C0", metaColor: "90989F", footerColor: "687078" },
  table: { headerBg: "1B6B7A", headerText: "FFFFFF", accentLine: "1B6B7A", innerLine: "C8DDE2", surface: "EDF3F5" },
  h1: "162235", h2: "1B6B7A", body: "1A2430", secondary: "5A6572",
};

const AR_FONT = { ascii: "Arial", hAnsi: "Arial", cs: "Arial" };
const CODE_FONT = { ascii: "Courier New", hAnsi: "Courier New", cs: "Courier New" };

const NB = { style: BorderStyle.NONE, size: 0, color: "auto" };
const allNoBorders = { top: NB, bottom: NB, left: NB, right: NB, insideHorizontal: NB, insideVertical: NB };
const cellNoBorders = { top: NB, bottom: NB, left: NB, right: NB };

function safeText(v, ph) {
  if (v === undefined || v === null || v === "" || String(v) === "NaN" || String(v) === "undefined") {
    return ph || "\u3010يُرجى تعبئته\u3011";
  }
  return String(v);
}

// ---------- runs ----------
function ar(text, opts = {}) {
  const size = opts.size || 24;
  return new TextRun({
    text: safeText(text), rightToLeft: true, font: AR_FONT,
    size, sizeComplexScript: size,
    bold: !!opts.bold, boldComplexScript: !!opts.bold,
    italics: !!opts.italics, color: opts.color || PAL.body,
  });
}

// LTR run for commands / paths / endpoints
function ltr(text, opts = {}) {
  const size = opts.size || 22;
  return new TextRun({
    text: safeText(text), font: opts.mono ? CODE_FONT : AR_FONT,
    size, sizeComplexScript: size, bold: !!opts.bold, color: opts.color || PAL.body,
  });
}

// ---------- paragraphs ----------
function pBody(text, opts = {}) {
  return new Paragraph({
    bidirectional: true, alignment: AlignmentType.JUSTIFIED,
    spacing: { line: 312, after: opts.after !== undefined ? opts.after : 120 },
    children: [ar(text, opts)],
  });
}

// paragraph from mixed runs (Arabic + inline LTR tokens)
function pRuns(runs, opts = {}) {
  return new Paragraph({
    bidirectional: true, alignment: opts.align || AlignmentType.JUSTIFIED,
    spacing: { line: 312, after: opts.after !== undefined ? opts.after : 120 },
    children: runs,
  });
}

// step lead-in: bold "الخطوة N —" + normal text, start-aligned (not justified per list rule)
function step(title, text, opts = {}) {
  return new Paragraph({
    bidirectional: true, alignment: AlignmentType.RIGHT,
    spacing: { line: 312, before: opts.before !== undefined ? opts.before : 160, after: 80 },
    children: [ar(title + " ", { bold: true, color: PAL.h2 }), ar(text)],
  });
}

function bullet(text, opts = {}) {
  return new Paragraph({
    bidirectional: true, alignment: AlignmentType.RIGHT,
    bullet: { level: 0 },
    spacing: { line: 312, after: 60 },
    children: [ar(text, opts)],
  });
}

function h1(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1, bidirectional: true, alignment: AlignmentType.RIGHT,
    spacing: { before: 400, after: 160, line: 380, lineRule: "atLeast" },
    children: [ar(text, { bold: true, size: 32, color: PAL.h1 })],
  });
}

function h2(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_2, bidirectional: true, alignment: AlignmentType.RIGHT,
    spacing: { before: 260, after: 120, line: 340, lineRule: "atLeast" },
    children: [ar(text, { bold: true, size: 28, color: PAL.h2 })],
  });
}

// caption before a table (keepNext binds it to the table)
function caption(text) {
  return new Paragraph({
    bidirectional: true, alignment: AlignmentType.RIGHT, keepNext: true,
    spacing: { before: 140, after: 80, line: 312 },
    children: [ar(text, { bold: true, size: 21, color: PAL.secondary })],
  });
}

// LTR code block, shaded, accent bar, soft-wrapped lines inside one paragraph
function codeBlock(text) {
  const lines = text.split("\n");
  const runs = [];
  lines.forEach((line, i) => {
    const t = line.length ? line : " ";
    if (i === 0) runs.push(new TextRun({ text: t, font: CODE_FONT, size: 19, color: "22303C" }));
    else runs.push(new TextRun({ text: t, font: CODE_FONT, size: 19, color: "22303C", break: 1 }));
  });
  return new Paragraph({
    alignment: AlignmentType.LEFT,
    spacing: { before: 100, after: 160, line: 264 },
    shading: { type: ShadingType.CLEAR, fill: "F1F5F9" },
    indent: { left: 240, right: 240 },
    border: {
      left: { style: BorderStyle.SINGLE, size: 14, color: PAL.table.accentLine, space: 8 },
      top: { style: BorderStyle.SINGLE, size: 2, color: PAL.table.innerLine, space: 4 },
      bottom: { style: BorderStyle.SINGLE, size: 2, color: PAL.table.innerLine, space: 4 },
      right: { style: BorderStyle.SINGLE, size: 2, color: PAL.table.innerLine, space: 8 },
    },
    children: runs,
  });
}

// ---------- tables (horizontal-only business style, RTL visual order) ----------
function cellPara(cell) {
  // cell: string | { t, ltr, bold, mono, color, size }
  const c = typeof cell === "string" ? { t: cell } : cell;
  const size = c.size || 21;
  if (c.ltr || c.mono) {
    return new Paragraph({
      alignment: AlignmentType.LEFT,
      spacing: { line: 288 },
      children: [ltr(c.t, { size, bold: c.bold, mono: c.mono, color: c.color })],
    });
  }
  return new Paragraph({
    bidirectional: true, alignment: AlignmentType.RIGHT,
    spacing: { line: 288 },
    children: [ar(c.t, { size, bold: c.bold, color: c.color })],
  });
}

function dataTable(headers, rows, widths) {
  const headerRow = new TableRow({
    tableHeader: true, cantSplit: true,
    children: headers.map((htext, i) => new TableCell({
      children: [new Paragraph({
        bidirectional: true, alignment: AlignmentType.RIGHT, spacing: { line: 288 },
        children: [ar(typeof htext === "string" ? htext : htext.t, { bold: true, size: 21, color: PAL.table.headerText })],
      })],
      shading: { type: ShadingType.CLEAR, fill: PAL.table.headerBg },
      margins: { top: 70, bottom: 70, left: 110, right: 110 },
      width: { size: widths[i], type: WidthType.PERCENTAGE },
    })),
  });
  const dataRows = rows.map((row, ri) => new TableRow({
    cantSplit: true,
    children: row.map((cell, i) => new TableCell({
      children: [cellPara(cell)],
      shading: (ri % 2 === 1) ? { type: ShadingType.CLEAR, fill: PAL.table.surface } : undefined,
      margins: { top: 60, bottom: 60, left: 110, right: 110 },
      width: { size: widths[i], type: WidthType.PERCENTAGE },
    })),
  }));
  return new Table({
    visuallyRightToLeft: true,
    width: { size: 100, type: WidthType.PERCENTAGE },
    borders: {
      top: { style: BorderStyle.SINGLE, size: 4, color: PAL.table.accentLine },
      bottom: { style: BorderStyle.SINGLE, size: 4, color: PAL.table.accentLine },
      left: NB, right: NB,
      insideHorizontal: { style: BorderStyle.SINGLE, size: 2, color: PAL.table.innerLine },
      insideVertical: NB,
    },
    rows: [headerRow, ...dataRows],
  });
}

// ---------- cover title layout (design-system.md calcTitleLayout, Arabic width model) ----------
function splitTitleLines(title, charsPerLine) {
  if (title.length <= charsPerLine) return [title];
  const breakAfter = new Set([..."،。؛：!؟", ..."-_/ \t"]);
  const lines = [];
  let remaining = title;
  while (remaining.length > charsPerLine) {
    let breakAt = -1;
    for (let i = charsPerLine; i >= Math.floor(charsPerLine * 0.6); i--) {
      if (i < remaining.length && breakAfter.has(remaining[i - 1])) { breakAt = i; break; }
    }
    if (breakAt === -1) {
      const limit = Math.min(remaining.length, Math.ceil(charsPerLine * 1.3));
      for (let i = charsPerLine + 1; i < limit; i++) {
        if (breakAfter.has(remaining[i - 1])) { breakAt = i; break; }
      }
    }
    if (breakAt === -1) breakAt = charsPerLine;
    lines.push(remaining.slice(0, breakAt).trim());
    remaining = remaining.slice(breakAt).trim();
  }
  if (remaining) lines.push(remaining);
  if (lines.length > 1 && lines[lines.length - 1].length <= 2) {
    const last = lines.pop();
    lines[lines.length - 1] += last;
  }
  return lines;
}

function calcTitleLayout(title, maxWidthTwips, preferredPt = 40, minPt = 24) {
  // Arabic glyphs are proportional: average width ≈ pt * 11 twips (vs pt*20 for CJK)
  const charWidth = (pt) => pt * 11;
  const charsPerLine = (pt) => Math.floor(maxWidthTwips / charWidth(pt));
  let titlePt = preferredPt, lines;
  while (titlePt >= minPt) {
    const cpl = charsPerLine(titlePt);
    if (cpl < 2) { titlePt -= 2; continue; }
    lines = splitTitleLines(title, cpl);
    if (lines.length <= 3) break;
    titlePt -= 2;
  }
  if (!lines || lines.length > 3) {
    lines = splitTitleLines(title, charsPerLine(minPt));
    titlePt = minPt;
  }
  return { titlePt, titleLines: lines };
}

function calcCoverSpacing(params) {
  const {
    titleLineCount = 1, titlePt = 36, hasSubtitle = false,
    hasEnglishLabel = false, metaLineCount = 0,
    fixedHeight = 800, pageHeight = 16838, marginTop = 0, marginBottom = 0,
  } = params;
  const SAFETY = 1200;
  const usableHeight = pageHeight - marginTop - marginBottom - SAFETY;
  const titleHeight = titleLineCount * (titlePt * 23 + 200);
  const subtitleHeight = hasSubtitle ? (12 * 23 + 600) : 0;
  const englishLabelHeight = hasEnglishLabel ? (9 * 23 + 600) : 0;
  const metaHeight = metaLineCount * (10 * 23 + 100);
  const implicitParaHeight = 3 * 300;
  const contentHeight = titleHeight + subtitleHeight + englishLabelHeight + metaHeight + fixedHeight + implicitParaHeight;
  const remainingSpace = usableHeight - contentHeight;
  const safeRemaining = Math.max(remainingSpace, 400);
  const FOOTER_MIN = 800;
  const rawTop = Math.floor(safeRemaining * 0.45);
  const rawBottom = Math.floor(safeRemaining * 0.45);
  const bottomSpacing = Math.max(rawBottom, FOOTER_MIN);
  const topSpacing = Math.max(rawTop - Math.max(0, FOOTER_MIN - rawBottom), 400);
  const midSpacing = Math.max(safeRemaining - topSpacing - bottomSpacing, 0);
  return { topSpacing, midSpacing, bottomSpacing };
}

// ---------- Recipe R1 (Pure Paragraph) mirrored for RTL ----------
function buildCoverR1RTL(config) {
  const P = config.palette;
  const padL = 800, padR = 1200; // mirrored: larger padding on the right (text side)
  const availableWidth = 11906 - padL - padR - 300;
  const { titlePt, titleLines } = calcTitleLayout(config.title, availableWidth, 40, 24);
  const titleSize = titlePt * 2;
  const spacing = calcCoverSpacing({
    titleLineCount: titleLines.length, titlePt,
    hasSubtitle: !!config.subtitle, hasEnglishLabel: !!config.englishLabel,
    metaLineCount: (config.metaLines || []).length,
    fixedHeight: 400, marginTop: 0, marginBottom: 0,
  });
  const accentRight = { style: BorderStyle.SINGLE, size: 8, color: P.accent, space: 12 };
  const children = [];

  // 1. dynamic top whitespace
  children.push(new Paragraph({ spacing: { before: spacing.topSpacing } }));

  // 2. English label with accent bottom border (right-aligned, mirrored)
  if (config.englishLabel) {
    children.push(new Paragraph({
      alignment: AlignmentType.RIGHT,
      indent: { right: padR, left: padL }, spacing: { after: 500 },
      border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: P.accent, space: 8 } },
      children: [new TextRun({
        text: config.englishLabel.split("").join("  "),
        size: 18, color: P.accent, font: { ascii: "Calibri", hAnsi: "Calibri", cs: "Arial" }, characterSpacing: 40,
      })],
    }));
  }

  // 3. main title — dynamic size, explicit line spacing (Rule 8)
  for (let i = 0; i < titleLines.length; i++) {
    children.push(new Paragraph({
      bidirectional: true, alignment: AlignmentType.RIGHT,
      indent: { right: padR, left: padL },
      spacing: { after: i < titleLines.length - 1 ? 100 : 300, line: Math.ceil(titlePt * 23), lineRule: "atLeast" },
      children: [ar(titleLines[i], { bold: true, size: titleSize, color: P.cover.titleColor })],
    }));
  }

  // 4. subtitle
  if (config.subtitle) {
    children.push(new Paragraph({
      bidirectional: true, alignment: AlignmentType.RIGHT,
      indent: { right: padR, left: padL }, spacing: { after: 800, line: 340, lineRule: "atLeast" },
      children: [ar(config.subtitle, { size: 24, color: P.cover.subtitleColor })],
    }));
  }

  // 5. meta lines with accent border on the right (mirrored from border.left)
  for (const line of (config.metaLines || [])) {
    children.push(new Paragraph({
      bidirectional: true, alignment: AlignmentType.RIGHT,
      indent: { right: padR + 200, left: padL }, spacing: { after: 80, line: 300 },
      border: { right: accentRight },
      children: [ar(line, { size: 24, color: P.cover.metaColor })],
    }));
  }

  // 6. dynamic bottom whitespace
  children.push(new Paragraph({ spacing: { before: spacing.bottomSpacing } }));

  // 7. footer with top accent separator
  children.push(new Paragraph({
    alignment: AlignmentType.RIGHT,
    indent: { right: padR, left: padL },
    border: { top: { style: BorderStyle.SINGLE, size: 2, color: P.accent, space: 8 } },
    spacing: { before: 200 },
    children: [
      new TextRun({ text: config.footerRight || "", size: 16, color: P.cover.footerColor, font: AR_FONT, rightToLeft: true }),
      new TextRun({ text: "                                   ", font: AR_FONT, size: 16 }),
      new TextRun({ text: config.footerLeft || "", size: 16, color: P.cover.footerColor, font: { ascii: "Calibri", hAnsi: "Calibri" } }),
    ],
  }));

  // single 16838 exact wrapper — allNoBorders, zero nested tables
  return [new Table({
    width: { size: 100, type: WidthType.PERCENTAGE },
    layout: TableLayoutType.FIXED,
    borders: allNoBorders,
    rows: [new TableRow({
      height: { value: 16838, rule: "exact" },
      children: [new TableCell({
        shading: { type: ShadingType.CLEAR, fill: P.bg },
        borders: cellNoBorders,
        children,
      })],
    })],
  })];
}

module.exports = {
  PAL, AR_FONT, CODE_FONT, allNoBorders, cellNoBorders,
  ar, ltr, pBody, pRuns, step, bullet, h1, h2, caption, codeBlock,
  dataTable, cellPara, calcTitleLayout, calcCoverSpacing, buildCoverR1RTL, safeText,
};
