import {
  artistReleaseCount,
  getArtistById,
  getArtists,
  getVisibleReleases,
  PLATFORM_ORDER,
  releaseCoverUrl,
  streamingLinks
} from "./content.js";

export interface ArtistRecord {
  id: string;
  name: string;
  image?: string | null;
  bio_short?: string | null;
  links?: Record<string, string | null>;
}

export interface ReleaseRecord {
  id: string;
  slug: string;
  title: string;
  artist_id: string;
  release_type?: string;
  release_date?: string | null;
  summary?: string | null;
  cover_image?: string | null;
  links?: Record<string, string | null>;
}

export interface ReleaseCardModel {
  slug: string;
  title: string;
  artistName: string;
  artistId: string;
  href: string;
  releaseType: string;
  releaseDate: string;
  coverImage: string;
  summary: string;
}

export interface ArtistCardModel {
  id: string;
  name: string;
  href: string;
  image?: string | null;
  summary: string;
  bioSummary: string;
  releaseCount: number;
  latestReleaseDate: string;
}

export function catalogArtists(): ArtistRecord[] {
  return getArtists() as ArtistRecord[];
}

export function releaseDateValue(release: ReleaseRecord): string {
  return release.release_date || "";
}

export function compareReleasesNewestFirst(left: ReleaseRecord, right: ReleaseRecord): number {
  const dateOrder = releaseDateValue(right).localeCompare(releaseDateValue(left));
  if (dateOrder !== 0) return dateOrder;
  return String(left.slug).localeCompare(String(right.slug));
}

export function catalogReleases(): ReleaseRecord[] {
  return [...(getVisibleReleases() as ReleaseRecord[])].sort(compareReleasesNewestFirst);
}

export function latestReleases(limit?: number): ReleaseCardModel[] {
  const releases = catalogReleases();
  return (limit === undefined ? releases : releases.slice(0, limit)).map(releaseCardModel);
}

export function releasesForArtist(artistId: string): ReleaseCardModel[] {
  return catalogReleases().filter((release) => release.artist_id === artistId).map(releaseCardModel);
}

export function artistCards(): ArtistCardModel[] {
  return catalogArtists().map((artist) => {
    const count = artistReleaseCount(artist.id);
    const latestReleaseDate = latestReleaseDateForArtist(artist.id);
    return {
      id: artist.id,
      name: artist.name,
      href: `/artists/${artist.id}/`,
      image: artist.image,
      releaseCount: count,
      latestReleaseDate,
      bioSummary: cleanSummary(artist.bio_short || artist.bio_long || ""),
      summary: `${count} public release${count === 1 ? "" : "s"}`
    };
  }).sort(compareArtistCardsByLatestRelease);
}

export function latestReleaseDateForArtist(artistId: string): string {
  return catalogReleases().find((release) => release.artist_id === artistId)?.release_date || "";
}

export function compareArtistCardsByLatestRelease(left: ArtistCardModel, right: ArtistCardModel): number {
  const dateOrder = right.latestReleaseDate.localeCompare(left.latestReleaseDate);
  if (dateOrder !== 0) return dateOrder;
  const countOrder = right.releaseCount - left.releaseCount;
  if (countOrder !== 0) return countOrder;
  return left.name.localeCompare(right.name);
}

export function releaseCardModel(release: ReleaseRecord): ReleaseCardModel {
  const artist = getArtistById(release.artist_id) as ArtistRecord | undefined;
  return {
    slug: release.slug,
    title: release.title,
    artistName: artist?.name || release.artist_id,
    artistId: release.artist_id,
    href: `/releases/${release.slug}/`,
    releaseType: release.release_type || "single",
    releaseDate: release.release_date || "",
    coverImage: releaseCoverUrl(release),
    summary: release.summary || ""
  };
}

export function releaseSocialLinks(release: ReleaseRecord): { label: string; href: string }[] {
  return streamingLinks(release);
}

const CORE_TRACK_PLATFORMS = new Set(["spotify", "apple_music", "youtube_music"]);

export function trackStreamingLinks(track: { links?: Record<string, string | null> }): { label: string; href: string | null }[] {
  const present = streamingLinks(track);
  const presentPlatforms = new Set(present.map((link) => link.label.replaceAll(" ", "_")));
  const missingCore = PLATFORM_ORDER.filter((platform) => CORE_TRACK_PLATFORMS.has(platform) && !presentPlatforms.has(platform))
    .map((platform) => ({ label: platform.replaceAll("_", " "), href: null }));
  return [...present, ...missingCore].sort(
    (left, right) => PLATFORM_ORDER.indexOf(left.label.replaceAll(" ", "_")) - PLATFORM_ORDER.indexOf(right.label.replaceAll(" ", "_"))
  );
}

export function artistStreamingLinks(artist: ArtistRecord): { label: string; href: string }[] {
  const platforms = new Set(PLATFORM_ORDER);
  return streamingLinks(artist).filter((link) => platforms.has(link.label.replaceAll(" ", "_")));
}

function cleanSummary(value: string): string {
  return String(value)
    .replace(/!\[[^\]]*\]\([^)]+\)/g, " ")
    .replace(/\[[^\]]*\]\([^)]+\)/g, " ")
    .replace(/^#{1,6}\s+/gm, " ")
    .replace(/\*\*([^*]+)\*\*/g, " $1 ")
    .replace(/__([^_]+)__/g, " $1 ")
    .replace(/\*([^*]+)\*/g, " $1 ")
    .replace(/_([^_]+)_/g, " $1 ")
    .replace(/\s+([,.;:!?])/g, "$1")
    .replace(/\s+/g, " ")
    .trim();
}
