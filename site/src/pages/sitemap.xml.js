import { getArtists, getAllTrackRouteParams, getMigratedRoutes, getVisibleReleases } from "../lib/content.js";

export async function GET() {
  const base = "https://www.maricoparecords.com";

  const releases = getVisibleReleases();
  const releaseDateBySlug = Object.fromEntries(releases.map((r) => [r.slug, r.release_date]));

  const staticPaths = ["/", "/artists/", "/releases/", "/posts/", "/about-us/", "/contact/"];

  const entries = [
    ...staticPaths.map((path) => ({ path, lastmod: null })),
    ...getArtists().map((a) => ({ path: `/artists/${a.id}/`, lastmod: null })),
    ...releases.map((r) => ({ path: `/releases/${r.slug}/`, lastmod: r.release_date || null })),
    ...getAllTrackRouteParams().map(({ slug, track }) => ({
      path: `/releases/${slug}/${track}/`,
      lastmod: releaseDateBySlug[slug] || null,
    })),
    ...getMigratedRoutes().map((e) => ({ path: e.normalized_path, lastmod: null })),
  ];

  const seen = new Set();
  const unique = entries.filter(({ path }) => {
    if (seen.has(path)) return false;
    seen.add(path);
    return true;
  });

  const urls = unique
    .map(({ path, lastmod }) => {
      const loc = `<loc>${base}${path}</loc>`;
      const mod = lastmod ? `<lastmod>${lastmod}</lastmod>` : "";
      return `  <url>${loc}${mod}</url>`;
    })
    .join("\n");

  const body = `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urls}\n</urlset>\n`;

  return new Response(body, {
    headers: { "Content-Type": "application/xml; charset=utf-8" },
  });
}
