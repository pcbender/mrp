import { getArtistById, getVisibleReleases } from "../lib/content.js";

export async function GET() {
  const base = "https://www.maricoparecords.com";
  const items = getVisibleReleases()
    .map((release) => {
      const artist = getArtistById(release.artist_id);
      return [
        "    <item>",
        `      <title>${escapeXml(release.title)} by ${escapeXml(artist?.name || release.artist_id)}</title>`,
        `      <link>${base}/releases/${release.slug}/</link>`,
        `      <guid>${base}/releases/${release.slug}/</guid>`,
        `      <description>${escapeXml(release.summary || release.seo.description)}</description>`,
        "    </item>"
      ].join("\n");
    })
    .join("\n");
  const body = `<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0">\n  <channel>\n    <title>Maricopa Records Releases</title>\n    <link>${base}/releases/</link>\n    <description>Latest releases from Maricopa Records.</description>\n${items}\n  </channel>\n</rss>\n`;

  return new Response(body, {
    headers: { "Content-Type": "application/rss+xml; charset=utf-8" }
  });
}

function escapeXml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}
