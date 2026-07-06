# Content Model

MRP content lives under `content/` and is designed to be edited by humans,
agents, or the admin UI, then validated against `mrp/schemas/*.schema.json`
before build/deploy. The schemas are the authority; this doc is orientation.

## Site

`content/site.yaml` stores label-level metadata such as canonical URL, label
name, publisher name, contact email, and timezone.

## Artists

Artist records live in `content/artists/{id}.yaml`
(`mrp/schemas/artist.schema.json`). Required: `artist.id`, `artist.name`,
`artist.visibility`. Artist IDs are lowercase slugs used in URLs
(`/artists/{id}/`) and as the key prefix for all downstream release
artifacts (see `docs/ADMIN-WORKSPACE.md`).

Beyond identity and platform `links` (artist pages on Spotify, Apple Music,
YouTube — the enrichment commands key off these), artist records carry the
promoter-managed profile: `promo_blurb`, `bio_short`, `bio_long`, and
`bio_auto_generated` (true until a human reviews and saves).

## Releases

Release records live in `content/releases/{slug}.yaml`
(`mrp/schemas/release.schema.json`). Two models:

- `song`: one single. `release_type: single`, track fields under `song:`.
- `album`: multi-track. `release_type: ep` or `album`, tracks under `tracks:`.

Skeleton of the current shape (see any live release for a full example,
e.g. `content/releases/on-to-potter-s-field.yaml`):

```yaml
release:
  id: signal-path
  slug: signal-path
  title: Signal Path
  artist_id: pcbender
  model: song
  release_type: single
  status: draft            # ladder: draft → staged → verified → approved → live
  release_date: '2026-01-01'
  label: Maricopa Records
  publisher: Maricopa Publishing
  upc:
  cover_image: site/public/assets/releases/signal-path/cover.jpg
  hero_image:
  summary:
  description:
  credits: { primary_artist:, songwriter:, lyrics:, producer:, mastering: }
  links:                   # release-level streaming links (11 platforms)
    spotify:
    apple_music:
    # ...
  seo: { title:, description: }
  automation:
    allow_auto_publish: false
    links_na: []           # platforms this release is not expected on
  song:
    number: 1
    title: Signal Path
    slug: signal-path
    isrc:
    duration:
    explicit: false
    preview_audio:         # /samples/{artist_id}--{slug}.mp3, written by sampler
    master_path:           # absolute path to the master WAV, used by sampler/critic
    lyrics_text:           # official lyrics (poem form)
    lyrics_raw:            # production text incl. Suno-style [section] tags
    style:                 # style/production prompt
    hints: {}              # human ground truth for the critic, e.g. Vocals: Male
    links: {}              # per-track streaming links
    credits: {}            # per-track credit overrides
    critic: {}             # saved critic settings: model/persona/target/target_tier
```

Create a draft from the CLI (`scripts/mrp release create --artist pcbender
--title "Signal Path" --type single`) or through the admin UI. Both refuse to
overwrite an existing release and validate the generated draft.

## Legacy content

`content/clone/`, `content/pages/`, and `content/posts/` hold frozen
WordPress-migration output — a different, closed content model. See
[CONTENT-PIPELINE.md](CONTENT-PIPELINE.md); do not create new records there.
