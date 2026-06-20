import { getArtistById, getMigratedPosts, getVisibleReleases, migratedDescription } from "../lib/content.js";

export async function GET() {
  const base = "https://www.maricoparecords.com";
  const releaseItems = getVisibleReleases()
    .map((release) => {
      const artist = getArtistById(release.artist_id);
      return [
        "    <item>",
        `      <title>${escapeXml(release.title)} by ${escapeXml(artist?.name || release.artist_id)}</title>`,
        `      <link>${base}/releases/${release.slug}/</link>`,
        `      <guid>${base}/releases/${release.slug}/</guid>`,
        `      <description>${escapeXml(release.summary || release.seo.description)}</description>`,
        release.release_date ? `      <pubDate>${rssDate(release.release_date)}</pubDate>` : "",
        "    </item>"
      ].filter(Boolean).join("\n");
    })
    .join("\n");
  const postItems = getMigratedPosts()
    .sort((left, right) => String(right.published_at || "").localeCompare(String(left.published_at || "")))
    .map((post) =>
      [
        "    <item>",
        `      <title>${escapeXml(post.title)}</title>`,
        `      <link>${base}/${post.slug}/</link>`,
        `      <guid>${base}/${post.slug}/</guid>`,
        `      <description>${escapeXml(migratedDescription(post))}</description>`,
        post.published_at ? `      <pubDate>${rssDate(post.published_at)}</pubDate>` : "",
        "    </item>"
      ].filter(Boolean).join("\n")
    )
    .join("\n");
  const items = [releaseItems, postItems].filter(Boolean).join("\n");
  const body = `<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0">\n  <channel>\n    <title>Maricopa Records</title>\n    <link>${base}/</link>\n    <description>Latest releases and posts from Maricopa Records.</description>\n${items}\n  </channel>\n</rss>\n`;

  return new Response(body, {
    headers: { "Content-Type": "application/rss+xml; charset=utf-8" }
  });
}

function escapeXml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replace(/[^\x00-\x7F]/g, (character) => `&#${character.codePointAt(0)};`);
}

function rssDate(value) {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? "" : date.toUTCString();
}
