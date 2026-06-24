import { existsSync, readdirSync, readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import yaml from "js-yaml";

const repoRoot = process.env.MRP_REPO_ROOT
  ? resolve(process.env.MRP_REPO_ROOT)
  : resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const publicRoot = resolve(repoRoot, "site/public");
const publicStatuses = new Set(["staged", "verified", "approved", "live"]);
const reservedMigratedPaths = new Set(["/", "/about-us/", "/artists/", "/contact/", "/posts/", "/releases/"]);
const localHosts = new Set(["maricoparecords.com", "www.maricoparecords.com"]);

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

export function getTrackBySlug(release, trackSlug) {
  return (release?.tracks || []).find((track) => track.slug === trackSlug);
}

export function getAllTrackRouteParams() {
  return getVisibleReleases().flatMap((release) =>
    (release.tracks || []).map((track) => ({ slug: release.slug, track: track.slug }))
  );
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

export const PLATFORM_ORDER = [
  "spotify",
  "apple_music",
  "youtube_music",
  "youtube",
  "tidal",
  "amazon_music",
  "deezer",
  "soundcloud",
  "bandcamp"
];

export function streamingLinks(record) {
  return Object.entries(record?.links || {})
    .filter(([key]) => key !== "landing_page")
    .filter(([, value]) => Boolean(value))
    .map(([key, href]) => ({ label: key.replaceAll("_", " "), href }))
    .sort((left, right) => platformRank(left.label) - platformRank(right.label));
}

function platformRank(label) {
  const index = PLATFORM_ORDER.indexOf(label.replaceAll(" ", "_"));
  return index === -1 ? PLATFORM_ORDER.length : index;
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

export function getClonePages() {
  return readRecords("content/clone/pages", "clone").filter((entry) => entry.route?.canonical_path);
}

export function getClonePosts() {
  return readRecords("content/clone/posts", "clone").filter((entry) => entry.route?.canonical_path);
}

export function getCloneRoutes() {
  const explicitRoutes = new Set([
    "/",
    "/about-us/",
    "/artists/",
    "/contact/",
    "/posts/",
    ...getArtists().map((artist) => `/artists/${artist.id}/`)
  ]);
  return [...getClonePages(), ...getClonePosts()]
    .map((entry) => ({
      ...entry,
      normalized_path: normalizePath(entry.route.canonical_path)
    }))
    .filter((entry) => !explicitRoutes.has(entry.normalized_path))
    .sort((left, right) => left.normalized_path.localeCompare(right.normalized_path));
}

export function getCloneByPath(path) {
  const normalized = normalizePath(path);
  return [...getClonePages(), ...getClonePosts()].find((entry) => normalizePath(entry.route.canonical_path) === normalized);
}

export function getCloneHeadManifest() {
  const path = resolve(repoRoot, "content/clone/head-manifest.yaml");
  if (!existsSync(path)) {
    return { shared: { stylesheets: [], scripts: [], preloads: [], inline_styles: [] }, pages: [] };
  }
  return yaml.load(readFileSync(path, "utf8"))?.clone_head || {
    shared: { stylesheets: [], scripts: [], preloads: [], inline_styles: [] },
    pages: []
  };
}

export function getCloneHeadForPath(path) {
  const manifest = getCloneHeadManifest();
  const normalized = normalizePath(path);
  return {
    shared: manifest.shared || { stylesheets: [], scripts: [], preloads: [], inline_styles: [] },
    page: (manifest.pages || []).find((entry) => normalizePath(entry.canonical_path) === normalized) || {
      stylesheets: [],
      scripts: [],
      preloads: [],
      inline_styles: []
    }
  };
}

export function clonePathParam(entry) {
  return entry.normalized_path.replace(/^\/|\/$/g, "");
}

export function cloneDescription(entry) {
  return entry.seo?.description || entry.excerpt || `${entry.title} on Maricopa Records.`;
}

export function renderCloneHtml(html) {
  return rewriteCloneUrls(String(html || ""));
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

export function renderMigratedHtml(html) {
  return rewriteMediaReferences(rewriteInternalLinks(String(html || "")));
}

function rewriteInternalLinks(html) {
  const routes = migratedRouteMap();
  return html.replace(/href=(["'])([^"']+)\1/g, (match, quote, href) => {
    const rewritten = rewriteInternalHref(href, routes);
    return `href=${quote}${rewritten}${quote}`;
  });
}

function rewriteCloneUrls(html) {
  const routes = cloneRouteMap();
  let rewritten = rewriteWordPressAssetReferences(html);
  rewritten = rewriteCssUrls(rewritten, routes);
  rewritten = rewriteSrcsets(rewritten, routes);
  rewritten = rewriteHtmlUrlAttributes(rewritten, routes);
  return rewritten;
}

function rewriteHtmlUrlAttributes(html, routes) {
  const urlAttributes = [
    "href",
    "src",
    "poster",
    "action",
    "data-src",
    "data-srcset",
    "data-bg",
    "data-background",
    "data-url",
    "xlink:href"
  ].join("|");
  const attributePattern = new RegExp(`\\b(${urlAttributes})=(["'])([^"']*)\\2`, "gi");
  return html.replace(attributePattern, (match, name, quote, value) => {
    if (name.toLowerCase().endsWith("srcset")) {
      return `${name}=${quote}${rewriteSrcsetValue(value, routes)}${quote}`;
    }
    return `${name}=${quote}${rewriteStaticUrl(value, routes)}${quote}`;
  });
}

function rewriteSrcsets(html, routes) {
  return html.replace(/\bsrcset=(["'])([^"']*)\1/gi, (match, quote, value) => {
    return `srcset=${quote}${rewriteSrcsetValue(value, routes)}${quote}`;
  });
}

function rewriteSrcsetValue(value, routes) {
  return value
    .split(",")
    .map((candidate) => {
      const trimmed = candidate.trim();
      if (!trimmed) return candidate;
      const [url, ...descriptors] = trimmed.split(/\s+/);
      return [rewriteStaticUrl(url, routes), ...descriptors].join(" ");
    })
    .join(", ");
}

function rewriteCssUrls(html, routes) {
  return html.replace(/url\(\s*(["']?)([^"')]+)\1\s*\)/gi, (match, quote, value) => {
    const rewritten = rewriteStaticUrl(value, routes);
    return `url(${quote}${rewritten}${quote})`;
  });
}

function rewriteInternalHref(href, routes) {
  if (href.startsWith("#") || href.startsWith("mailto:") || href.startsWith("tel:") || href.startsWith("javascript:")) {
    return href;
  }
  let parsed;
  try {
    parsed = new URL(href, "https://www.maricoparecords.com");
  } catch {
    return href;
  }
  if (!localHosts.has(parsed.hostname)) {
    return href;
  }
  const normalized = normalizePath(parsed.pathname);
  const rewritten = routes.get(normalized);
  if (!rewritten) {
    return href;
  }
  return `${rewritten}${parsed.search}${parsed.hash}`;
}

function rewriteStaticUrl(value, routes) {
  if (!value || value.startsWith("#") || isNonHttpUrl(value)) {
    return value;
  }
  const asset = wordpressAssetPath(value);
  if (asset) {
    return asset;
  }
  let parsed;
  try {
    parsed = new URL(value, "https://www.maricoparecords.com");
  } catch {
    return value;
  }
  if (!localHosts.has(parsed.hostname)) {
    return value;
  }
  const normalized = normalizePath(parsed.pathname);
  const rewritten = routes.get(normalized);
  if (!rewritten) {
    return value;
  }
  return `${rewritten}${parsed.search}${parsed.hash}`;
}

function isNonHttpUrl(value) {
  return /^(?:mailto|tel|sms|javascript|data|blob):/i.test(value);
}

function migratedRouteMap() {
  const routes = new Map([
    ["/", "/"],
    ["/about-us/", "/about-us/"],
    ["/artists/", "/artists/"],
    ["/contact/", "/contact/"],
    ["/posts/", "/posts/"],
    ["/releases/", "/releases/"]
  ]);
  for (const artist of getArtists()) {
    routes.set(`/artists/${artist.id}/`, `/artists/${artist.id}/`);
  }
  for (const release of getVisibleReleases()) {
    routes.set(`/releases/${release.slug}/`, `/releases/${release.slug}/`);
  }
  for (const entry of getMigratedRoutes()) {
    routes.set(entry.normalized_path, entry.canonical_path || entry.normalized_path);
  }
  return routes;
}

function cloneRouteMap() {
  const routes = migratedRouteMap();
  for (const entry of [...getClonePages(), ...getClonePosts()]) {
    const canonical = normalizePath(entry.route.canonical_path);
    routes.set(canonical, canonical);
    for (const alias of entry.route.aliases || []) {
      routes.set(normalizePath(alias), canonical);
    }
  }
  return routes;
}

function rewriteMediaReferences(html) {
  return html.replace(/(?:https?:\/\/(?:www\.)?maricoparecords\.com)?\/wp-content\/[^\s"'<>),\\]+/g, (url) => {
    const localPath = localMigratedAssetPath(url);
    return localPath || url;
  });
}

function rewriteWordPressAssetReferences(html) {
  return html.replace(/(?:https?:\/\/(?:www\.)?maricoparecords\.com)?\/(?:wp-content|wp-includes)\/[^\s"'<>),\\]+/g, (url) => {
    return wordpressAssetPath(url) || url;
  });
}

function wordpressAssetPath(url) {
  let parsed;
  try {
    parsed = new URL(url, "https://www.maricoparecords.com");
  } catch {
    return null;
  }
  if (!localHosts.has(parsed.hostname)) {
    return null;
  }
  const path = decodeURIComponent(parsed.pathname);
  if (!path.startsWith("/wp-content/") && !path.startsWith("/wp-includes/")) {
    return null;
  }
  return `/assets/wp${path}`;
}

function localMigratedAssetPath(url) {
  let parsed;
  try {
    parsed = new URL(url, "https://www.maricoparecords.com");
  } catch {
    return null;
  }
  if (!localHosts.has(parsed.hostname) || !parsed.pathname.startsWith("/wp-content/")) {
    return null;
  }
  const normalizedUrl = `https://www.maricoparecords.com${decodeURIComponent(parsed.pathname)}`;
  const digest = createHash("sha256").update(normalizedUrl).digest("hex").slice(0, 12);
  const basename = safeFilename(decodeURIComponent(parsed.pathname.split("/").pop() || "asset"));
  const publicPath = `/assets/migrated/${digest}-${basename}`;
  return existsSync(resolve(publicRoot, publicPath.replace(/^\//, ""))) ? publicPath : null;
}

function safeFilename(value) {
  const normalized = value.normalize("NFKD").replace(/[^\x00-\x7F]/g, "");
  return normalized.replace(/[^A-Za-z0-9._-]+/g, "-").replace(/^[.-]+|[.-]+$/g, "") || "asset";
}
