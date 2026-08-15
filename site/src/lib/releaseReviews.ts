export interface ReviewableRelease {
  artist_id?: string;
  artistId?: string;
  slug: string;
  model?: string;
  release_type?: string;
  releaseType?: string;
  song?: { slug?: string | null } | null;
  tracks?: unknown[] | null;
}

/** Return the critic writeback id for a release, regardless of release type. */
export function releaseReviewId(release: ReviewableRelease): string {
  const artistId = release.artist_id || release.artistId || "";
  const releaseType = release.release_type || release.releaseType || "";
  const isMultiTrack =
    release.model === "album" ||
    releaseType === "album" ||
    releaseType === "ep" ||
    Array.isArray(release.tracks);

  if (isMultiTrack) {
    return `album--${artistId}--${release.slug}`;
  }

  return `${artistId}--${release.song?.slug || release.slug}`;
}
