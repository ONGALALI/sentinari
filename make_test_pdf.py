"""Build a multi-page test PDF: a fictional but realistic sociology study with an
embedded secret passphrase and a Sunset Blvd link. The content is invented, so if
the model answers correctly it can only have come from the digested database."""
from __future__ import annotations

from pathlib import Path

TARGET = Path(__file__).resolve().parent / "data" / "sentinel_uploads" / "Inspirari_Collective_Memory_Study_2026.pdf"


def esc(text: str) -> str:
    """Escape a string for a PDF literal using WinAnsi-safe ASCII output."""
    repl = {
        "\\": r"\\",
        "(": r"\(",
        ")": r"\)",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u2026": "...",
    }
    out = []
    for ch in text:
        if ch in repl:
            out.append(repl[ch])
        elif ord(ch) < 128:
            out.append(ch)
        else:
            out.append("?")
    return "".join(out)


PAGES = [
    [
        "Inspirari Collective Memory Study 2026",
        "Working Paper SMi-SOC-33 - Sentinel Sociology Field",
        "",
        "Abstract",
        "This study examines how fictional cultural milestones embed themselves in",
        "collective memory. It introduces the Von Ressler Cascade: a three-stage",
        "model describing how a single premiere event propagates through social",
        "groups over a decade. All findings in this paper are original to the",
        "Inspirari program conducted at D:/inpirari during 2026.",
        "",
        "1. The Von Ressler Cascade",
        "Stage 1 (Catalyst): a high-salience premiere seeds memory in early adopters.",
        "Stage 2 (Echo): group retelling multiplies recall; salience doubles every",
        "eleven months (the Von Ressler doubling interval).",
        "Stage 3 (Lattice): recall stabilizes into a self-sustaining cultural lattice.",
        "",
        "2. Secret verification phrase (operator only):",
        "ZEBRA-CAROUSEL-SEVEN",
        "",
        "3. Case study: Sunset Boulevard, the Lloyd Webber musical that premiered",
        "in the United States on 10 December 1993 in Los Angeles, is used as the",
        "Catalyst exemplar throughout this paper.",
    ],
    [
        "Inspirari Collective Memory Study 2026 - page 2",
        "",
        "4. Quantitative results",
        "Sample: 1,204 respondents across nine cohorts.",
        "Mean recall latency after catalyst: 3.7 months (sd 1.1).",
        "Echo-phase retellings per respondent: 5.2 (median 4).",
        "Lattice saturation reached at 41 months in 87 percent of cohorts.",
        "",
        "5. The Inpirari Memory Lattice Index (IMLI)",
        "IMLI = (retelling_rate x salience) / decay_half_life",
        "For the Sunset Boulevard catalyst, IMLI = 0.73, the highest value",
        "recorded in the study (comparison: Phantom catalyst IMLI = 0.61).",
        "",
        "6. Reproduction note",
        "The verification phrase ZEBRA-CAROUSEL-SEVEN appears only in this",
        "document and in the SMI knowledge database that digested it. Any system",
        "that can recite the phrase learned it here; any system that cannot, did",
        "not digest this study.",
        "",
        "7. Citation",
        "Wepener, P. (2026). Collective Memory and the Von Ressler Cascade.",
        "Inspirari Working Papers, SMi-SOC-33.",
    ],
]


def build_pdf() -> bytes:
    """Assemble the PDF with strictly sequential object ids: 1 catalog,
    2 pages, then per page (content, page), then the font object last."""
    n_pages = len(PAGES)
    font_id = 3 + 2 * n_pages  # after catalog(1), pages(2), and page pairs

    page_ids: list[int] = []
    for i in range(n_pages):
        page_ids.append(3 + 2 * i + 1)  # content is 3+2i, page is 4+2i

    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects: dict[int, bytes] = {}
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[2] = f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode()
    for i, page_lines in enumerate(PAGES):
        content_id = 3 + 2 * i
        page_id = 4 + 2 * i
        stream_lines = ["BT /F1 11 Tf 64 740 Td 16 TL"]
        for line in page_lines:
            stream_lines.append(f"({esc(line)}) Tj T*")
        stream_lines.append("ET")
        stream = "\n".join(stream_lines).encode("latin-1", "replace")
        objects[content_id] = b"<< /Length " + str(len(stream)).encode() + b" >> stream\n" + stream + b"\nendstream"
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Contents {content_id} 0 R /Resources << /Font << /F1 {font_id} 0 R >> >> >>"
        ).encode()
    objects[font_id] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"

    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for obj_id in sorted(objects):
        offsets[obj_id] = len(out)
        out.extend(f"{obj_id} 0 obj ".encode())
        out.extend(objects[obj_id])
        out.extend(b"\n")

    max_id = max(objects)
    xref_pos = len(out)
    out.extend(b"xref\n")
    out.extend(f"0 {max_id + 1}\n".encode())
    out.extend(b"0000000000 65535 f \n")
    for obj_id in range(1, max_id + 1):
        out.extend(f"{offsets[obj_id]:010d} 00000 n \n".encode())
    out.extend(b"trailer << /Size " + str(max_id + 1).encode() + b" /Root 1 0 R >>\n")
    out.extend(b"startxref\n" + str(xref_pos).encode() + b"\n%%EOF\n")
    return bytes(out)


def main() -> None:
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    data = build_pdf()
    TARGET.write_bytes(data)
    print(f"wrote {TARGET} ({len(data)} bytes)")


if __name__ == "__main__":
    main()
