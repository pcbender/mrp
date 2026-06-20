import { cloneDescription, getClonePosts, getMigratedPosts, migratedDescription, normalizePath } from "./content.js";

const postImages = {
  "a-conversation-with-echo": "/assets/wp/wp-content/uploads/2025/02/Echo-Conversation.jpg",
  "how-ai-music-generation-will-disrupt-the-traditional-music-industry-and-artists": "/assets/wp/wp-content/uploads/2025/02/Disruption-of-the-traditional-music-industry-by-AI.jpg",
  "the-future-of-ai-in-music": "/assets/wp/wp-content/uploads/2025/02/MaricopaRecordsWithTag.png"
};

function entrySlug(entry) {
  return entry.source?.slug || entry.slug || String(entry.route?.canonical_path || entry.normalized_path || "")
    .split("/")
    .filter(Boolean)
    .at(-1);
}

export function postUrl(entry) {
  return normalizePath(entry.route?.canonical_path || entry.normalized_path || `/${entrySlug(entry)}/`);
}

export function postDate(entry) {
  if (entry.published_at) {
    return String(entry.published_at).slice(0, 10);
  }
  const match = postUrl(entry).match(/^\/(\d{4})\/(\d{2})\/(\d{2})\//);
  return match ? `${match[1]}-${match[2]}-${match[3]}` : "";
}

export function postImage(entry) {
  return postImages[entrySlug(entry)] || "/assets/maricopa-mark.svg";
}

export function postExcerpt(entry) {
  return entry.route ? cloneDescription(entry) : migratedDescription(entry);
}

export function allStructuredPosts() {
  const posts = new Map();
  for (const post of getMigratedPosts()) {
    posts.set(entrySlug(post), post);
  }
  for (const post of getClonePosts()) {
    posts.set(entrySlug(post), post);
  }
  return [...posts.values()].sort((left, right) => postDate(right).localeCompare(postDate(left)));
}

export function relatedPosts(currentEntry, limit = 2) {
  const currentPath = postUrl(currentEntry);
  return allStructuredPosts().filter((post) => postUrl(post) !== currentPath).slice(0, limit);
}
