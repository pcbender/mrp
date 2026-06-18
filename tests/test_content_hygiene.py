import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANONICAL_CONTENT_DIRS = [
    ROOT / "content" / "artists",
    ROOT / "content" / "pages",
    ROOT / "content" / "posts",
    ROOT / "content" / "releases",
    ROOT / "site" / "src" / "content",
]
FORBIDDEN_CANONICAL_ARTIFACTS = re.compile(
    r"wp-block|<!--\s*/?\s*wp:|\bstk-|/wp-content/(?:plugins|themes)/",
    re.IGNORECASE,
)


def test_canonical_content_excludes_wordpress_block_artifacts():
    offenders = []
    for directory in CANONICAL_CONTENT_DIRS:
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*")):
            if path.suffix not in {".json", ".yaml", ".yml", ".md", ".mdx"}:
                continue
            text = path.read_text()
            if FORBIDDEN_CANONICAL_ARTIFACTS.search(text):
                offenders.append(str(path.relative_to(ROOT)))

    assert offenders == []
