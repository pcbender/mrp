import { existsSync, readdirSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import yaml from "js-yaml";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const publicStatuses = new Set(["staged", "verified", "approved", "live"]);
const reservedMigratedPaths = new Set(["/", "/about-us/", "/artists/", "/catalog/", "/contact/", "/posts/", "/releases/"]);

function readRecords(relativeDir, rootKey) {
  const dir = resolve(repoRoot, relativeDir);
  if (!existsSync(dir)) return [];
  return readdirSync(dir)
    .filter((name) => name.endsWith(".json") || name.endsWith(".yaml") || name.endsWith(".yml"))
    .sort()
    .map((name) => {
      const text = readFileSync(resolve(dir, name), "utf8");
      const data = name.endsWith(".json") ? JSON.parse(text) : yaml.load(text);
      return data[rootKey];
    })
    .filter(Boolean);
}

export function getArtists() {
  return readRecords("content/artists", "artist").filter((artist) => artist.visibility === "public");
}

export function getAllReleases() {
  return readRecords("content/releases", "release");
}

export function getVisibleReleases() {
  const includeDrafts = process.env.MRP_PREVIEW_DRAFTS === "1";
  return getAllReleases().filter((release) => includeDrafts || publicStatuses.has(release.status));
}

export function getArtistById(id) {
  return getArtists().find((artist) => artist.id === id);
}

export function getReleaseBySlug(slug) {
  return getVisibleReleases().find((release) => release.slug === slug);
}

export function latestRelease() {
  return [...getVisibleReleases()].sort((left, right) =>
    String(right.release_date || "").localeCompare(String(left.release_date || ""))
  )[0];
}

export function artistReleaseCount(artistId) {
  return getVisibleReleases().filter((release) => release.artist_id === artistId).length;
}

export function releaseCoverUrl(release) {
  const cover = release?.cover_image || "";
  const marker = "site/public";
  if (cover.startsWith(marker)) {
    return cover.slice(marker.length);
  }
  return "/assets/maricopa-mark.svg";
}

export function streamingLinks(release) {
  return Object.entries(release?.links || {})
    .filter(([, value]) => Boolean(value))
    .map(([key, href]) => ({ label: key.replaceAll("_", " "), href }));
}

export function getMigratedPages() {
  return readRecords("content/pages", "page").filter((page) => page.slug && page.content_html);
}

export function getMigratedPosts() {
  return readRecords("content/posts", "post").filter((post) => post.slug && post.content_html);
}

export function getMigratedRoutes() {
  const currentRoutes = new Set([
    ...getArtists().map((artist) => `/artists/${artist.id}/`),
    ...getVisibleReleases().map((release) => `/releases/${release.slug}/`)
  ]);
  return [...getMigratedPages(), ...migratedPostRouteEntries()]
    .map((entry) => ({
      ...entry,
      normalized_path: normalizePath(entry.normalized_path || `/${entry.slug}/`)
    }))
    .filter((entry) => !reservedMigratedPaths.has(entry.normalized_path))
    .filter((entry) => !currentRoutes.has(entry.normalized_path))
    .sort((left, right) => left.normalized_path.localeCompare(right.normalized_path));
}

function migratedPostRouteEntries() {
  return getMigratedPosts().flatMap((post) => {
    const primaryPath = normalizePath(post.normalized_path || `/${post.slug}/`);
    const aliases = getRedirects()
      .map((redirect) => normalizePath(redirect.source_path))
      .filter((path) => path.endsWith(`/${post.slug}/`) && path !== primaryPath)
      .map((path) => ({ ...post, normalized_path: path, canonical_path: primaryPath }));
    return [{ ...post, normalized_path: primaryPath }, ...aliases];
  });
}

function getRedirects() {
  const path = resolve(repoRoot, "content/redirects.yaml");
  if (!existsSync(path)) return [];
  return yaml.load(readFileSync(path, "utf8"))?.redirects || [];
}

export function migratedPathParam(entry) {
  return entry.normalized_path.replace(/^\/|\/$/g, "");
}

export function migratedDescription(entry) {
  return entry.seo?.description || entry.excerpt || `${entry.title} on Maricopa Records.`;
}

export function normalizePath(path) {
  const value = `/${String(path || "").replace(/^\/|\/$/g, "")}/`;
  return value === "//" ? "/" : value;
}
