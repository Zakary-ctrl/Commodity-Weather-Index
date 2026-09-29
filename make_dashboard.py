"""Assemble le site à publier.

- site/ : index.html + world.js + data.js + normals.js (GitHub Pages, ou ouverture locale)
- dist/observatoire.html : version autonome, tout inclus (publication en Artifact Claude)
"""
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
D, SITE = ROOT / "dashboard", ROOT / "site"


def main() -> None:
    app = (D / "app.html").read_text()
    latest = (ROOT / "data" / "latest.json").read_text()
    normals_f = ROOT / "data" / "normals.json"
    normals = normals_f.read_text() if normals_f.exists() else "{}"
    SITE.mkdir(exist_ok=True)
    shutil.copy(D / "world.js", SITE / "world.js")
    (SITE / "data.js").write_text("window.OSC_DATA = " + json.dumps(json.loads(latest), ensure_ascii=False) + ";\n")
    (SITE / "normals.js").write_text("window.OSC_NORMALS = " + normals + ";\n")
    scripts = '<script src="world.js"></script>\n<script src="normals.js"></script>\n<script src="data.js"></script>'
    (SITE / "index.html").write_text(
        '<!doctype html>\n<html lang="fr"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
        '<meta name="description" content="Anomalies météo des grandes ceintures agricoles mondiales et leur lecture pour les marchés de soft commodities.">'
        "</head><body>\n" + app.replace("<!--DATA-->", scripts) + "\n</body></html>\n")
    (SITE / ".nojekyll").write_text("")
    inline = "".join(f"<script>{(SITE / f).read_text()}</script>\n" for f in ("world.js", "normals.js", "data.js"))
    (ROOT / "dist").mkdir(exist_ok=True)
    (ROOT / "dist" / "observatoire.html").write_text(app.replace("<!--DATA-->", inline))
    print("OK : site/index.html et dist/observatoire.html")


if __name__ == "__main__":
    main()
