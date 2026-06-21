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


def test_latest_releases_defaults_to_full_catalog(tmp_path):
    script = tmp_path / "catalog-latest-test.mjs"
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
            const {{ catalogReleases, latestReleases }} = await import(pathToFileURL(modulePath).href);
            console.log(JSON.stringify({{
              catalog: catalogReleases().length,
              latest: latestReleases().length,
              limited: latestReleases(6).length
            }}));
            """
        )
    )

    result = subprocess.run(["node", str(script)], cwd=ROOT / "site", text=True, capture_output=True, check=False)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["latest"] == payload["catalog"]
    assert payload["limited"] == 6


def test_artist_releases_are_newest_first_and_link_to_release_pages(tmp_path):
    script = tmp_path / "catalog-artist-test.mjs"
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
            const {{ releasesForArtist }} = await import(pathToFileURL(modulePath).href);
            const releases = releasesForArtist("pcbender");
            console.log(JSON.stringify(releases.map((item) => ({{
              slug: item.slug,
              href: item.href,
              releaseDate: item.releaseDate
            }}))));
            """
        )
    )

    result = subprocess.run(["node", str(script)], cwd=ROOT / "site", text=True, capture_output=True, check=False)

    assert result.returncode == 0, result.stderr
    releases = json.loads(result.stdout)
    assert releases
    assert [release["releaseDate"] for release in releases] == sorted(
        [release["releaseDate"] for release in releases],
        reverse=True,
    )
    assert all(release["href"] == f"/releases/{release['slug']}/" for release in releases)


def test_artist_cards_sort_by_latest_release_newest_first(tmp_path):
    script = tmp_path / "catalog-artist-cards-test.mjs"
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
            const {{ artistCards }} = await import(pathToFileURL(modulePath).href);
            console.log(JSON.stringify(artistCards().map((item) => ({{
              id: item.id,
              latestReleaseDate: item.latestReleaseDate
            }}))));
            """
        )
    )

    result = subprocess.run(["node", str(script)], cwd=ROOT / "site", text=True, capture_output=True, check=False)

    assert result.returncode == 0, result.stderr
    artists = json.loads(result.stdout)
    assert [artist["id"] for artist in artists] == ["pcbender", "stab", "4castle", "lingua-aeternum"]
    assert [artist["latestReleaseDate"] for artist in artists] == ["2025-03-29", "2025-03-29", "2025-03-29", ""]


def test_catalog_components_are_used_by_dynamic_pages():
    page_imports = {
        "site/src/pages/index.astro": ["latestReleases", "artistCards"],
        "site/src/pages/artists/[slug].astro": ["releasesForArtist"],
        "site/src/pages/artists/index.astro": ["artistCards"],
        "site/src/pages/releases/index.astro": ["catalogReleases", "releaseCardModel"],
    }
    for rel_path, expected_imports in page_imports.items():
        text = (ROOT / rel_path).read_text()
        assert "../lib/catalog" in text or "../../lib/catalog" in text
        for expected in expected_imports:
            assert expected in text


def test_releases_index_uses_release_browser():
    text = (ROOT / "site/src/pages/releases/index.astro").read_text()

    assert 'import ReleaseBrowser from "../../components/ReleaseBrowser.astro";' in text
    assert "<ReleaseBrowser releases={releases} rich />" in text


def test_artist_release_list_uses_release_browser_in_center_column():
    text = (ROOT / "site/src/components/ArtistReleaseList.astro").read_text()

    assert 'import ReleaseBrowser from "./ReleaseBrowser.astro";' in text
    assert 'class="artist-release-list page-grid centered-page"' in text
    assert "<ReleaseBrowser releases={releases} rich />" in text
