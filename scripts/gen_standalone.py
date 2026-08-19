"""Generate notebooks/gate1_standalone.py from config.py.

The standalone script has to run with no repo present, so it necessarily
duplicates the channel ids, buckets and keywords. Generating it from the
single source of truth means the duplication cannot drift by hand;
tests/test_standalone.py then verifies the generated result independently.

    python -m scripts.gen_standalone
"""

from __future__ import annotations

import json
from pathlib import Path

from . import config as cfg

TEMPLATE = Path(__file__).resolve().parent / "gate1_template.py"
OUT = Path(__file__).resolve().parents[1] / "notebooks" / "gate1_standalone.py"


def render_buckets() -> str:
    lines = ["BUCKETS = {"]
    for b in cfg.ICT_BUCKETS:
        lines.append(f"    {json.dumps(b.display_name)}: [")
        row: list[str] = []
        for kw in b.all_keywords:
            row.append(json.dumps(kw))
        # Wrap at a sensible width for readability when pasted.
        line = "        "
        for item in row:
            if len(line) + len(item) + 2 > 88:
                lines.append(line.rstrip())
                line = "        "
            line += item + ", "
        if line.strip():
            lines.append(line.rstrip())
        lines.append("    ],")
    lines.append("}")
    return "\n".join(lines)


def main() -> int:
    text = TEMPLATE.read_text(encoding="utf-8")
    replacements = {
        "@@ICT_CHANNEL@@": json.dumps(cfg.channel("ICT").channel_id),
        "@@NBB_CANDIDATES@@": json.dumps(cfg.NBB_CANDIDATE_IDS),
        "@@ICT_MAX@@": str(cfg.ICT_ENUMERATION_MAX),
        "@@NBB_MAX@@": str(cfg.NBB_ENUMERATION_MAX),
        "@@GUEST_QUERIES@@": json.dumps(cfg.GUEST_APPEARANCE_QUERIES),
        "@@SEARCH_MAX@@": str(cfg.SEARCH_QUERY_MAX_RESULTS),
        "@@BUCKETS@@": render_buckets(),
    }
    for marker, value in replacements.items():
        if marker not in text:
            raise SystemExit(f"template is missing marker {marker}")
        text = text.replace(marker, value)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT} ({len(text.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
