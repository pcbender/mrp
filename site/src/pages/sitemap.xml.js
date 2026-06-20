import { getArtists, getMigratedRoutes, getVisibleReleases } from "../lib/content.js";

export async function GET() {
  const base = "https://www.maricoparecords.com";
  const paths = [
    "/",
    "/artists/",
    "/releases/",
    "/posts/",
    "/about-us/",
    "/contact/",
    ...getArtists().map((artist) => `/artists/${artist.id}/`),
    ...getVisibleReleases().map((release) => `/releases/${release.slug}/`),
    ...getMigratedRoutes().map((entry) => entry.normalized_path)
  ].filter((path, index, allPaths) => allPaths.indexOf(path) === index);
  const body = `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${paths
    .map((path) => `  <url><loc>${base}${path}</loc></url>`)
    .join("\n")}\n</urlset>\n`;

  return new Response(body, {
    headers: { "Content-Type": "application/xml; charset=utf-8" }
  });
}
