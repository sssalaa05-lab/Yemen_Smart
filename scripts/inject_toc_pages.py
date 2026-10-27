#!/usr/bin/env python3
"""inject_toc_pages.py — fill docx-js cached TOC PAGEREF results with real page numbers.
Reads a JSON mapping {anchor(_TocN): page_number}, splits each merged PAGEREF run
(begin+instr+separate+end in one w:r) and inserts a result run with the page text.
"""
import re, shutil, sys, zipfile, json

DOCX = sys.argv[1]
PAGE_MAP = json.loads(sys.argv[2])  # {"_Toc1": "1", ...}

with zipfile.ZipFile(DOCX, "r") as z:
    names = z.namelist()
    data = {n: z.read(n) for n in names}
xml = data["word/document.xml"].decode("utf-8")

# ensure settings.xml has updateFields=true (Word prompts to refresh TOC on open)
settings = data["word/settings.xml"].decode("utf-8")
if "w:updateFields" in settings:
    settings = re.sub(r"<w:updateFields\s*/>", '<w:updateFields w:val="true"/>', settings)
    settings = re.sub(r'<w:updateFields w:val="(false|0)"\s*/>', '<w:updateFields w:val="true"/>', settings)
else:
    settings = settings.replace("<w:zoom", '<w:updateFields w:val="true"/><w:zoom', 1)
    if "w:updateFields" not in settings:
        settings = settings.replace("</w:settings>", '<w:updateFields w:val="true"/></w:settings>')
data["word/settings.xml"] = settings.encode("utf-8")
print("settings.xml updateFields ensured")

injected = 0
def patch_block(m):
    global injected
    block = m.group(0)
    anchor = m.group(1)
    page = PAGE_MAP.get(anchor)
    if not page or 'w:fldCharType="separate"' not in block:
        return block
    new_block, n = re.subn(
        r'(<w:fldChar w:fldCharType="separate"/>)(<w:fldChar w:fldCharType="end"/>)',
        r'\1</w:r><w:r><w:t xml:space="preserve">' + str(page) + r'</w:t></w:r><w:r>\2',
        block, count=1, flags=re.S,
    )
    if n:
        injected += 1
    return new_block

xml = re.sub(
    r'<w:hyperlink[^>]*w:anchor="(_Toc\d+)"[^>]*>.*?</w:hyperlink>',
    patch_block, xml, flags=re.S,
)
print(f"injected page numbers into {injected} PAGEREF results")

data["word/document.xml"] = xml.encode("utf-8")
TMP = DOCX + ".tmp.zip"
with zipfile.ZipFile(TMP, "w", zipfile.ZIP_DEFLATED) as z:
    for n in names:
        z.writestr(n, data[n])
shutil.move(TMP, DOCX)
print("OK", DOCX)
