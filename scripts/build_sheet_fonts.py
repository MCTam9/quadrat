"""Build the static Archivo cuts the PDF sheet uses, from Google Fonts' variable Archivo.

The web app sets Archivo with its width axis (expanded for the site name and key figures).
matplotlib cannot choose variable-font axes, so the sheet ships static instances, subset to
Latin plus the symbols the sheet prints. Run once when the cuts change; the output is committed
to sce/report/fonts/ with the SIL Open Font License alongside.

    curl -LO 'https://github.com/google/fonts/raw/main/ofl/archivo/Archivo%5Bwdth,wght%5D.ttf'
    python scripts/build_sheet_fonts.py 'Archivo[wdth,wght].ttf'
"""

from __future__ import annotations

import sys
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

OUT = Path(__file__).resolve().parent.parent / "sce" / "report" / "fonts"
# (file, family, style, weight, width). 118 % width is the web app's `.wide` class.
CUTS = (
    ("Archivo-Regular.ttf", "Archivo", "Regular", 400, 100),
    ("Archivo-SemiBold.ttf", "Archivo", "SemiBold", 600, 100),
    ("ArchivoExpanded-SemiBold.ttf", "Archivo Expanded", "SemiBold", 600, 118),
    ("ArchivoExpanded-Bold.ttf", "Archivo Expanded", "Bold", 700, 118),
)
# En/em dash, quotes, bullet, ellipsis, primes, arrows, minus, super 2/3, degree, middle dot,
# times, comparisons, phi, thin and narrow no-break spaces.
SYMBOLS = (
    0x2013, 0x2014, 0x2018, 0x2019, 0x201C, 0x201D, 0x2022, 0x2026, 0x2032, 0x2033,
    0x2190, 0x2191, 0x2192, 0x2193, 0x2212, 0x00B2, 0x00B3, 0x00B0, 0x00B7, 0x00D7,
    0x2264, 0x2265, 0x2248, 0x03C6, 0x2009, 0x202F,
)  # fmt: skip
UNICODES = [*range(0x20, 0x7F), *range(0xA0, 0x180), *SYMBOLS]


def build(source: Path) -> None:
    for filename, family, style, weight, width in CUTS:
        font = instantiateVariableFont(TTFont(source), {"wght": weight, "wdth": width})
        for table in ("DSIG", "STAT"):
            if table in font:
                del font[table]
        name = font["name"]
        postscript = f"{family}-{style}".replace(" ", "")
        legacy_family = family if style == "Regular" else f"{family} {style}"
        for rec in list(name.names):
            if rec.nameID in (1, 2, 3, 4, 6, 16, 17, 25):
                name.removeNames(nameID=rec.nameID)
        for nid, value in (
            (1, legacy_family),
            (2, "Regular"),
            (3, f"{postscript};quadrat-static"),
            (4, f"{family} {style}"),
            (6, postscript),
            (16, family),
            (17, style),
        ):
            name.setName(value, nid, 3, 1, 0x409)
            name.setName(value, nid, 1, 0, 0)
        font["OS/2"].usWeightClass = weight
        options = subset.Options()
        options.layout_features = ["kern", "liga", "tnum", "lnum", "case"]
        options.name_IDs = ["*"]
        options.notdef_outline = True
        subsetter = subset.Subsetter(options)
        subsetter.populate(unicodes=UNICODES)
        subsetter.subset(font)
        font.save(OUT / filename)
        print(f"{filename}: {(OUT / filename).stat().st_size // 1024} KB")


if __name__ == "__main__":
    build(Path(sys.argv[1]))
