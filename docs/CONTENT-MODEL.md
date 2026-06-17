# Content Model

MRP content lives under `content/` and is designed to be edited by humans or
agents, then validated before build/deploy.

## Site

`content/site.yaml` stores label-level metadata such as canonical URL, label
name, publisher name, contact email, and timezone.

## Artists

Artist records live in `content/artists/`.

Required fields:

- `artist.id`
- `artist.name`
- `artist.visibility`

Artist IDs are lowercase slugs and are used in generated artist URLs:

```text
/artists/{artist.id}/
```

## Releases

Release records live in `content/releases/`. MRP v0.1 has two models:

- `song`: one song/single. `release_type` must be `single`.
- `album`: multi-track release. `release_type` is `ep` or `album`.

EPs and albums share the same template shape with `tracks`; the release type
distinguishes the public category.

Example draft single:

```yaml
release:
  id: signal-path
  slug: signal-path
  title: Signal Path
  artist_id: pcbender
  model: song
  release_type: single
  status: draft
  release_date:
  label: Maricopa Records
  publisher: Maricopa Publishing
  upc:
  catalog_number:
  cover_image: assets/releases/signal-path/cover.jpg
  hero_image:
  summary: ""
  description: ""
  credits:
    primary_artist: pcbender
    songwriter:
    producer:
    mastering:
  links:
    spotify:
    apple_music:
    youtube_music:
    bandcamp:
    soundcloud:
    landing_page:
  seo:
    title: Signal Path by pcbender
    description: Signal Path by pcbender on Maricopa Records.
  automation:
    allow_auto_publish: false
  song:
    number:
    title: Signal Path
    slug: signal-path
    isrc:
    duration:
    explicit: false
    preview_audio:
    lyrics_excerpt:
```

Create a draft from the CLI:

```bash
scripts/mrp release create --artist pcbender --title "Signal Path" --type single
```

The command writes `content/releases/{slug}.yaml`, creates
`assets/releases/{slug}/`, refuses overwrite, and validates the generated draft.

## WordPress Static Clone

WXR-derived clone content lives under `content/clone/` and is separate from the
curated MRP publishing records:

- `content/clone/pages/` stores static pages, artist pages, and release pages.
- `content/clone/posts/` stores blog/news posts.
- `content/clone/assets/manifest.yaml` tracks WordPress assets referenced by
  cloned HTML.

Clone records use a single `clone` schema with `kind` distinguishing
`static_page`, `artist_page`, `release_page`, and `blog_post`. The record keeps
the WordPress source ID, post type, post status, source link, canonical path,
aliases, and raw WXR `content_html`.

This model is intentionally not the same as `content/artists/` or
`content/releases/`. The clone layer preserves WordPress page content for the
Astro static clone; the publishing layer remains the curated MRP release model.
