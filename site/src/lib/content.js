import { existsSync, readdirSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const publicStatuses = new Set(["staged", "verified", "approved", "live"]);

function readJsonRecords(relativeDir, rootKey) {
  const dir = resolve(repoRoot, relativeDir);
  if (!existsSync(dir)) return [];
  return readdirSync(dir)
    .filter((name) => name.endsWith(".json"))
    .sort()
    .map((name) => JSON.parse(readFileSync(resolve(dir, name), "utf8"))[rootKey]);
}

export function getArtists() {
  return readJsonRecords("content/artists", "artist").filter((artist) => artist.visibility === "public");
}

export function getAllReleases() {
  return readJsonRecords("content/releases", "release");
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
