from mrp.core.wp_normalize import normalize_wordpress_content


def test_normalize_wordpress_content_extracts_semantic_fields():
    html = """
    <!-- wp:stackable/text {"uniqueId":"abc"} -->
    <div class="wp-block-stackable-text stk-block-text stk-abc">
      <p class="stk-block-text__text">Hello <strong>catalog</strong>.</p>
    </div>
    <!-- /wp:stackable/text -->
    [child_pages thumbs="true"]
    <div class="wp-block-stackable-image stk-block-image">
      <figure><img class="stk-img" src="https://www.maricoparecords.com/wp-content/uploads/cover.jpg" alt="Cover"></figure>
    </div>
    <a class="stk-link" href="https://open.spotify.com/artist/abc">Spotify</a>
    """

    result = normalize_wordpress_content(html, "content/pages/example.yaml")

    assert "wp-block" not in result.content_html
    assert "stk-" not in result.content_html
    assert "wp:" not in result.content_html
    assert "<p>Hello <strong>catalog</strong>.</p>" in result.content_html
    assert "![Cover](https://www.maricoparecords.com/wp-content/uploads/cover.jpg)" in result.content_markdown
    assert result.sections == [{"type": "artist_releases"}]
    assert result.images == [
        {
            "src": "https://www.maricoparecords.com/wp-content/uploads/cover.jpg",
            "alt": "Cover",
        }
    ]
    assert result.socials == {"spotify": "https://open.spotify.com/artist/abc"}
    assert result.unresolved_artifacts == []
