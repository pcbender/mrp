import json
import subprocess
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_catalog_sorts_releases_newest_first_with_slug_tiebreaker(tmp_path):
    script = tmp_path / "catalog-sort-test.mjs"
    script.write_text(
        textwrap.dedent(
            f"""
            import {{ pathToFileURL }} from "node:url";
            import {{ readFileSync, writeFileSync }} from "node:fs";
            import ts from "{ROOT / "site/node_modules/typescript/lib/typescript.js"}";

            const catalogPath = "{ROOT / "site/src/lib/catalog.ts"}";
            const contentUrl = pathToFileURL("{ROOT / "site/src/lib/content.js"}").href;
            const source = readFileSync(catalogPath, "utf8").replace(
              'from "./content.js"',
              `from ${{JSON.stringify(contentUrl)}}`
            );
            const output = ts.transpileModule(source, {{
              compilerOptions: {{
                module: ts.ModuleKind.ES2022,
                target: ts.ScriptTarget.ES2022
              }}
            }}).outputText;
            const modulePath = "{tmp_path / "catalog.mjs"}";
            writeFileSync(modulePath, output);
            const {{ compareReleasesNewestFirst }} = await import(pathToFileURL(modulePath).href);
            const releases = [
              {{ slug: "bravo", release_date: "2025-01-02" }},
              {{ slug: "charlie", release_date: "2025-01-01" }},
              {{ slug: "alpha", release_date: "2025-01-02" }}
            ];
            console.log(JSON.stringify(releases.sort(compareReleasesNewestFirst).map((item) => item.slug)));
            """
        )
    )

    result = subprocess.run(["node", str(script)], cwd=ROOT / "site", text=True, capture_output=True, check=False)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == ["alpha", "bravo", "charlie"]


def test_catalog_components_are_used_by_dynamic_pages():
    page_imports = {
        "site/src/pages/index.astro": ["latestReleases", "artistCards"],
        "site/src/pages/artists/[slug].astro": ["releasesForArtist"],
        "site/src/pages/releases/index.astro": ["catalogReleases", "releaseCardModel"],
    }
    for rel_path, expected_imports in page_imports.items():
        text = (ROOT / rel_path).read_text()
        assert "../lib/catalog" in text or "../../lib/catalog" in text
        for expected in expected_imports:
            assert expected in text
