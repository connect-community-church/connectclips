"""Render docs/operator-manual.md to docs/operator-manual.pdf.

Markdown → HTML (python-markdown) → PDF (Playwright/Chromium print to PDF).
A temp HTML is written into docs/ so relative image paths (screenshots/...)
resolve correctly during rendering, then deleted.
"""

from pathlib import Path

import markdown
from playwright.sync_api import sync_playwright

DOCS = Path("/home/connectadmin/ConnectClips/docs")
MD = DOCS / "operator-manual.md"
PDF = DOCS / "operator-manual.pdf"
TMP_HTML = DOCS / "_operator-manual.tmp.html"

CSS = """
@page {
  size: Letter;
  margin: 0.6in 0.7in;
}
* { box-sizing: border-box; }
html, body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  font-size: 11pt;
  line-height: 1.45;
  color: #1a1f24;
}
h1 {
  font-size: 22pt;
  margin-top: 0;
  margin-bottom: 0.3em;
  color: #0c1117;
  border-bottom: 2px solid #2a323d;
  padding-bottom: 6px;
}
h2 {
  font-size: 16pt;
  margin-top: 1.2em;
  margin-bottom: 0.4em;
  color: #0c1117;
  page-break-after: avoid;
}
h3 {
  font-size: 13pt;
  margin-top: 1em;
  margin-bottom: 0.3em;
  page-break-after: avoid;
}
p, li { margin: 0.4em 0; }
strong { color: #0c1117; }
code {
  background: #f4f3ec;
  border: 1px solid #e5e4e7;
  border-radius: 3px;
  padding: 1px 5px;
  font-size: 0.92em;
}
pre {
  background: #f4f3ec;
  border: 1px solid #e5e4e7;
  border-radius: 4px;
  padding: 8px 10px;
  font-size: 0.9em;
  overflow-x: auto;
  page-break-inside: avoid;
}
pre code { background: transparent; border: none; padding: 0; }
img {
  max-width: 100%;
  height: auto;
  border: 1px solid #d4d4d4;
  border-radius: 4px;
  display: block;
  margin: 8px 0;
  page-break-inside: avoid;
}
table {
  border-collapse: collapse;
  width: 100%;
  margin: 8px 0;
  page-break-inside: avoid;
  font-size: 0.95em;
}
th, td {
  border: 1px solid #d0d7de;
  padding: 5px 8px;
  text-align: left;
  vertical-align: top;
}
th { background: #f6f8fa; }
hr {
  border: none;
  border-top: 1px solid #d0d7de;
  margin: 1em 0;
}
ul, ol { padding-left: 1.4em; }
blockquote {
  border-left: 3px solid #d0d7de;
  margin: 0.6em 0;
  padding: 0 0.8em;
  color: #555;
}
/* Each major section starts on a fresh page (except the first) */
h2 { break-before: page; }
h2:first-of-type { break-before: avoid; }
"""


def main():
    md_text = MD.read_text(encoding="utf-8")
    body_html = markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "attr_list", "sane_lists"],
    )
    full_html = f"""<!doctype html>
<html><head>
<meta charset="utf-8">
<title>ConnectClips Operator's Manual</title>
<style>{CSS}</style>
</head><body>
{body_html}
</body></html>
"""
    TMP_HTML.write_text(full_html, encoding="utf-8")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context()
            page = ctx.new_page()
            page.goto(TMP_HTML.absolute().as_uri(), wait_until="networkidle")
            page.pdf(
                path=str(PDF),
                format="Letter",
                margin={"top": "0.6in", "bottom": "0.6in", "left": "0.7in", "right": "0.7in"},
                print_background=True,
            )
            browser.close()
    finally:
        TMP_HTML.unlink(missing_ok=True)

    print(f"wrote {PDF} ({PDF.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
