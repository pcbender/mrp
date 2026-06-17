import json
import subprocess
import sys
from pathlib import Path

from mrp.core.migration_inventory import DEFAULT_MIGRATION_SOURCE
from mrp.core.wxr import classify_wxr_item, parse_wxr, wxr_inventory


ROOT = Path(__file__).resolve().parents[1]
SOURCE = DEFAULT_MIGRATION_SOURCE


def write_wxr(path: Path) -> None:
    path.write_text(
        """<?xml version="1.0" encoding="UTF-8" ?>
<rss version="2.0"
  xmlns:excerpt="http://wordpress.org/export/1.2/excerpt/"
  xmlns:content="http://purl.org/rss/1.0/modules/content/"
  xmlns:dc="http://purl.org/dc/elements/1.1/"
  xmlns:wp="http://wordpress.org/export/1.2/">
  <channel>
    <title>Maricopa Records</title>
    <link>https://www.maricoparecords.com</link>
    <description>Test export</description>
    <wp:wxr_version>1.2</wp:wxr_version>
    <wp:base_site_url>https://www.maricoparecords.com</wp:base_site_url>
    <wp:base_blog_url>https://www.maricoparecords.com</wp:base_blog_url>
    <item>
      <title>PCBender</title>
      <link>https://www.maricoparecords.com/artists/pcbender/</link>
      <pubDate>Wed, 11 Jun 2025 19:34:00 +0000</pubDate>
      <dc:creator><![CDATA[mrp]]></dc:creator>
      <guid isPermaLink="false">https://www.maricoparecords.com/?page_id=791</guid>
      <content:encoded><![CDATA[<p>part mystique, part circuitry</p>
<div class="wp-block-stackable-column">Controls stay raw.</div>]]></content:encoded>
      <excerpt:encoded><![CDATA[A short artist bio.]]></excerpt:encoded>
      <wp:post_id>791</wp:post_id>
      <wp:post_date><![CDATA[2025-06-11 12:34:00]]></wp:post_date>
      <wp:post_date_gmt><![CDATA[2025-06-11 19:34:00]]></wp:post_date_gmt>
      <wp:post_modified><![CDATA[2025-06-12 12:34:00]]></wp:post_modified>
      <wp:post_modified_gmt><![CDATA[2025-06-12 19:34:00]]></wp:post_modified_gmt>
      <wp:post_name><![CDATA[pcbender]]></wp:post_name>
      <wp:status><![CDATA[publish]]></wp:status>
      <wp:post_parent>0</wp:post_parent>
      <wp:menu_order>2</wp:menu_order>
      <wp:post_type><![CDATA[page]]></wp:post_type>
      <category domain="artist" nicename="pcbender"><![CDATA[PCBender]]></category>
      <wp:postmeta>
        <wp:meta_key><![CDATA[_thumbnail_id]]></wp:meta_key>
        <wp:meta_value><![CDATA[921]]></wp:meta_value>
      </wp:postmeta>
    </item>
    <item>
      <title>Cart</title>
      <link>https://www.maricoparecords.com/cart/</link>
      <guid isPermaLink="false">https://www.maricoparecords.com/?page_id=3</guid>
      <content:encoded><![CDATA[<p>Cart shortcode</p>]]></content:encoded>
      <wp:post_id>3</wp:post_id>
      <wp:post_name><![CDATA[cart]]></wp:post_name>
      <wp:status><![CDATA[publish]]></wp:status>
      <wp:post_type><![CDATA[page]]></wp:post_type>
    </item>
    <item>
      <title>Contact feedback</title>
      <link>https://www.maricoparecords.com/?feedback=1</link>
      <guid isPermaLink="false">https://www.maricoparecords.com/?feedback=1</guid>
      <wp:post_id>11</wp:post_id>
      <wp:post_name><![CDATA[feedback-1]]></wp:post_name>
      <wp:status><![CDATA[publish]]></wp:status>
      <wp:post_type><![CDATA[feedback]]></wp:post_type>
    </item>
    <item>
      <title>PCBender image</title>
      <link>https://www.maricoparecords.com/pcbender-image/</link>
      <guid isPermaLink="false">https://www.maricoparecords.com/wp-content/uploads/pcbender.png</guid>
      <wp:post_id>921</wp:post_id>
      <wp:post_name><![CDATA[pcbender-image]]></wp:post_name>
      <wp:status><![CDATA[inherit]]></wp:status>
      <wp:post_type><![CDATA[attachment]]></wp:post_type>
      <wp:attachment_url><![CDATA[https://www.maricoparecords.com/wp-content/uploads/pcbender.png]]></wp:attachment_url>
    </item>
  </channel>
</rss>
""",
        encoding="utf-8",
    )


def run_mrp(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "mrp.cli.main", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_parse_wxr_preserves_namespaced_fields_and_raw_content(tmp_path):
    wxr = tmp_path / "fixture.xml"
    write_wxr(wxr)

    result = parse_wxr(wxr)

    assert result["channel"]["wxr_version"] == "1.2"
    assert result["summary"]["items"] == 4
    item = result["items"][0]
    assert item["id"] == "791"
    assert item["slug"] == "pcbender"
    assert item["guid"]["is_permalink"] is False
    assert item["creator"] == "mrp"
    assert item["menu_order"] == 2
    assert item["terms"] == [{"domain": "artist", "nicename": "pcbender", "name": "PCBender"}]
    assert item["postmeta"] == [{"key": "_thumbnail_id", "value": "921"}]
    assert "<div class=\"wp-block-stackable-column\">Controls stay raw.</div>" in item["content_html"]
    assert "part mystique, part circuitry" in item["content_html"]


def test_classify_wxr_items_explicitly_marks_clone_scope_and_exclusions(tmp_path):
    wxr = tmp_path / "fixture.xml"
    write_wxr(wxr)
    items = parse_wxr(wxr)["items"]

    categories = {item["slug"]: classify_wxr_item(item)["category"] for item in items}

    assert categories["pcbender"] == "artist_page"
    assert categories["cart"] == "excluded_commerce"
    assert categories["feedback-1"] == "excluded_feedback"
    assert categories["pcbender-image"] == "attachment"


def test_wxr_inventory_reads_real_export_and_capture_manifest(tmp_path):
    repo = tmp_path / "repo"

    result = wxr_inventory(repo, SOURCE)

    assert result["status"] == "passed"
    assert result["command"] == "wxr-inventory"
    assert result["summary"]["wxr_items"] == 375
    assert result["summary"]["captured_pages"] == 52
    assert result["summary"]["captured_assets"] == 664
    assert result["summary"]["post_types"]["feedback"] == 136
    assert result["summary"]["post_types"]["product"] == 8
    assert result["summary"]["categories"]["excluded_feedback"] == 136
    assert result["summary"]["categories"]["excluded_commerce"] == 12
    assert result["summary"]["categories"]["blog_news_post"] == 3
    assert result["summary"]["categories"]["artist_page"] >= 1
    assert result["summary"]["categories"]["release_page"] >= 1
    assert result["content_checks"]["pcbender_mystique"] is True
    assert result["exclusions"]["commerce"]
    assert result["exclusions"]["feedback"]
    assert (repo / result["report_path"]).is_file()


def test_wxr_inventory_cli_outputs_json(tmp_path):
    repo = tmp_path / "repo"

    result = run_mrp("--repo", str(repo), "--json", "wxr-inventory", "--source", str(SOURCE))

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["command"] == "wxr-inventory"
    assert payload["status"] == "passed"
    assert payload["content_checks"]["pcbender_mystique"] is True
    assert (repo / payload["report_path"]).is_file()


def test_wxr_inventory_missing_source_fails_cleanly(tmp_path):
    repo = tmp_path / "repo"
    missing_source = tmp_path / "missing"

    result = run_mrp("--repo", str(repo), "--json", "wxr-inventory", "--source", str(missing_source))

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert payload["stage"] == "config"
    assert "Could not find website migration artifacts" in payload["message"]
    assert (repo / payload["report_path"]).is_file()
