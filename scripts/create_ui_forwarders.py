"""
Create physical forwarders in docs/ui/... for GitHub Pages
"""

from pathlib import Path

DOCS_DIR = Path(r"D:\Sentinari\docs")

FORWARDER_TEMPLATE = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Redirecting to {title}...</title>
  <meta http-equiv="refresh" content="0; url=../../{target}">
  <script>window.location.replace('../../{target}');</script>
</head>
<body style="background:#0a1118; color:#fff; font-family:sans-serif; text-align:center; padding-top:20vh;">
  <p>Redirecting to <a href="../../{target}" style="color:#00e5ff;">{title}</a>...</p>
</body>
</html>
"""

forwarders = [
    ("oncology", "oncology.html", "Oncology Precision"),
    ("threats", "threats.html", "Planetary Threat Matrix"),
    ("vision", "vision.html", "Vision Lab & 3D Anatomy"),
    ("help", "help.html", "Help Manual"),
    ("skills", "skills.html", "Skills Matrix"),
]

for sub, target, title in forwarders:
    p = DOCS_DIR / "ui" / sub
    p.mkdir(parents=True, exist_ok=True)
    idx = p / "index.html"
    idx.write_text(FORWARDER_TEMPLATE.format(target=target, title=title), encoding="utf-8")
    print(f"Created forwarder at {idx}")
