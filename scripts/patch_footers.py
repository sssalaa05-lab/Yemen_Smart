#!/usr/bin/env python3
"""patch_footers.py — WPS compatibility post-processing per docx skill toc.md:
1. Map each sectPr's footerReference r:id -> footer file via rels
2. Section 2 (front matter) footer: PAGE -> PAGE \\* ROMAN \\* MERGEFORMAT
   Section 3 (body) footer:        PAGE -> PAGE \\* arabic \\* MERGEFORMAT
3. Remove empty <w:pgNumType/> elements from document.xml
"""
import re, shutil, sys, zipfile, os

DOCX = sys.argv[1] if len(sys.argv) > 1 else "/home/z/my-project/download/Nexus-Setup-Guide-AR.docx"
TMP = DOCX + ".tmp.zip"

with zipfile.ZipFile(DOCX, "r") as z:
    names = z.namelist()
    data = {n: z.read(n) for n in names}

doc_xml = data["word/document.xml"].decode("utf-8")
rels_xml = data["word/_rels/document.xml.rels"].decode("utf-8")

# rel id -> target footer file
rel_map = dict(re.findall(r'<Relationship[^>]*Id="([^"]+)"[^>]*Target="(footer\d+\.xml)"', rels_xml))
# also handle attribute order variants
for m in re.finditer(r'<Relationship\b[^>]*/>', rels_xml):
    tag = m.group(0)
    rid = re.search(r'Id="([^"]+)"', tag)
    tgt = re.search(r'Target="(footer\d+\.xml)"', tag)
    if rid and tgt:
        rel_map[rid.group(1)] = tgt.group(1)

# sectPr blocks in document order (section1 cover, 2 front matter, 3 body)
sect_blocks = re.findall(r"<w:sectPr\b.*?</w:sectPr>", doc_xml, flags=re.S)
print(f"sections found: {len(sect_blocks)}")

def footer_of(block):
    m = re.search(r'<w:footerReference[^>]*w:type="default"[^>]*r:id="([^"]+)"', block)
    if not m:
        m = re.search(r'<w:footerReference[^>]*r:id="([^"]+)"', block)
    return rel_map.get(m.group(1)) if m else None

targets = {}
if len(sect_blocks) >= 3:
    f_roman = footer_of(sect_blocks[1])
    f_arabic = footer_of(sect_blocks[2])
    if f_roman: targets[f_roman] = "ROMAN"
    if f_arabic: targets[f_arabic] = "arabic"
print("footer patch plan:", targets)

for fname, fmt in targets.items():
    key = "word/" + fname
    if key not in data:
        print("WARN missing", key); continue
    xml = data[key].decode("utf-8")
    xml, n = re.subn(
        r"(<w:instrText[^>]*>)\s*PAGE\s*(</w:instrText>)",
        rf"\1 PAGE \\* {fmt} \\* MERGEFORMAT \2",
        xml,
    )
    data[key] = xml.encode("utf-8")
    print(f"patched {fname}: {n} field(s) -> {fmt}")

# remove empty pgNumType (docx-js emits it on the cover section)
doc_xml, n_removed = re.subn(r"<w:pgNumType/>", "", doc_xml)
print(f"removed empty pgNumType: {n_removed}")
data["word/document.xml"] = doc_xml.encode("utf-8")

with zipfile.ZipFile(TMP, "w", zipfile.ZIP_DEFLATED) as z:
    for n in names:
        z.writestr(n, data[n])
shutil.move(TMP, DOCX)
print("OK", DOCX)
