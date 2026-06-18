import {
  artistReleaseCount,
  getArtistById,
  getArtists,
  getVisibleReleases,
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
  releaseCount: number;
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

export function latestReleases(limit = 6): ReleaseCardModel[] {
  return catalogReleases().slice(0, limit).map(releaseCardModel);
}

export function releasesForArtist(artistId: string): ReleaseCardModel[] {
  return catalogReleases().filter((release) => release.artist_id === artistId).map(releaseCardModel);
}

export function artistCards(): ArtistCardModel[] {
  return catalogArtists().map((artist) => {
    const count = artistReleaseCount(artist.id);
    return {
      id: artist.id,
      name: artist.name,
      href: `/artists/${artist.id}/`,
      image: artist.image,
      releaseCount: count,
      summary: `${count} public release${count === 1 ? "" : "s"}`
    };
  });
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
