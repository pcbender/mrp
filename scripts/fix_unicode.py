"""One-shot script: re-encode active content YAML files with allow_unicode=True."""
import yaml
from pathlib import Path

ACTIVE_DIRS = [
    "content/releases",
    "content/artists",
    "content/pages",
    "content/posts",
]

changed = 0
for dir_ in ACTIVE_DIRS:
    for path in sorted(Path(dir_).glob("*.yaml")):
        original = path.read_text()
        data = yaml.safe_load(original)
        if data is None:
            continue
        reencoded = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
        if reencoded != original:
            path.write_text(reencoded)
            print(f"re-encoded {path}")
            changed += 1
        else:
            print(f"unchanged  {path}")

print(f"\n{changed} file(s) updated.")
