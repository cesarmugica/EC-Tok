"""Mete las traducciones (tools/i18n_ui.py) en src/web/index.html, entre /* I18N-START */ y /* I18N-END */."""
import json
import re
from pathlib import Path

from i18n_ui import T
from i18n_zh import ZH

root = Path(__file__).resolve().parent.parent
page = root / "src" / "web" / "index.html"
faltan = [k for k in T if k not in ZH]
if faltan:
    print(f"⚠ {len(faltan)} textos sin chino (salen en español):", *faltan[:5], sep="\n  ")
data = {"en": {k: v[0] for k, v in T.items()}, "pt": {k: v[1] for k, v in T.items()}, "zh": {k: ZH[k] for k in T if k in ZH}}
text = page.read_text(encoding="utf-8")
block = "/* I18N-START */ const I18N = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "; /* I18N-END */"
new, n = re.subn(r"/\* I18N-START \*/.*?/\* I18N-END \*/", lambda _m: block, text, flags=re.S)
assert n == 1, "faltan las marcas I18N en index.html"
page.write_text(new, encoding="utf-8")
print(f"{len(T)} textos traducidos (en, pt, zh)")
