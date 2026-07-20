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

An artist record may also carry the internal likeness pair, never rendered
on the public site:

- `reference_image` — repo-relative path (convention:
  `assets/artists/{id}/reference.{ext}`; members use
  `assets/artists/{id}/members/{slug}.{ext}`) to the base likeness
  reference. It lives under the git-tracked `assets/` tree — not
  `site/public/` — so it is versioned and rides the admin Changes
  workflow but is never published. The public `image` is refreshed over
  time by generating new renders *from* this reference.
- `likeness_notes` — visual-identity prompt notes for generation
  consistency (promoter pipeline). For solo/project/persona acts this is
  the act's own likeness; for bands it can hold band-wide visual language,
  while per-person likeness lives on `members[].likeness_notes` (see
  below).

### Members (bands)

A band artist (`type: band`) may carry an optional `members` array. Members
are **embedded** in the band's artist record — they are not standalone files
and have no URLs of their own. Each member:

```yaml
members:
  - slug: raven-cortez        # required; ^[a-z0-9][a-z0-9-]*$, unique within the band
    name: Raven Cortez        # required
    roles: [lead guitar, vocals]  # optional
    status: current           # optional: current | former | guest
    display_order: 1          # optional; sort order on the artist page
    image:                    # optional; site-relative path (public)
    reference_image:          # optional; repo-relative path under
                              # assets/artists/{id}/members/ — internal
                              # base likeness, git-tracked, never published
    likeness_notes:           # optional; visual-identity prompt notes for
                              # generation consistency (promoter pipeline)
    bio:                      # optional; blank lines separate paragraphs
```

The artist page renders `current`/`guest` members (name, roles, bio, image),
ordered by `display_order`. A member slug is referenced from a release only
within that member's own band (see `performers` below).

## Releases

Release records live in `content/releases/{slug}.yaml`
(`mrp/schemas/release.schema.json`). A release has exactly one of two shapes:

- `song`: a single-track release. `release_type: single`; its one track is
  stored under `song:`.
- `album`: a multi-track release with at least two tracks. `release_type: ep`
  or `album`; every track is an item under `tracks:`.

Both `song` and each `tracks[]` item use the same track contract. Track-owned
fields—including `master_path`, `stems`, lyrics, credits, links, and
`music_video`—belong inside that individual track object, never at the release
root. A music video therefore always belongs to exactly one track, regardless
of whether that track is the single release's `song` or one item in an EP or
album's `tracks` array.

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

### Optional stems and music-video production state

An individual track may add an internal `stems` array without changing the
meaning or validity of older records. The master remains in `master_path`; it is not
duplicated as a stem. Each stem has a stable slug-like `id`, a local `path`,
and one of the semantic roles `drums`, `bass`, `vocals`, `instruments`, or
`other`. `label` and `enabled` are optional. Multiple stems may share a role,
but their IDs must be unique within the track.

```yaml
song:
  master_path: /mnt/c/Masters/signal-path.wav
  stems:
    - id: lead-vocal
      label: Lead vocal
      role: vocals
      path: /mnt/c/Stems/Signal Path/Lead Vocal.wav
      enabled: true
```

A track may also reference versioned music-video source state. The object is
optional; when present, `project` is the canonical repo-relative
`assets/source/video/{artist_id}--{track_slug}/project.yaml` path and `status`
is one of `draft`, `timed`, `cast`, `previewed`, `rendered`, `approved`, or
`published`. `public_url` and `poster` are optional public URL/site-path fields
and remain null until publication owns stable public media.

```yaml
song:
  music_video:
    project: assets/source/video/pcbender--signal-path/project.yaml
    status: cast
    public_url:
    poster:
```

`master_path`, every `stems[].path`, the internal project path, and all
`assets/processed/video/` paths are private production data. Astro pages,
JSON-LD, browser payloads, and public manifests must never contain them. The
presence of a project or render state alone does not make a video public.

Create a draft from the CLI (`scripts/mrp release create --artist pcbender
--title "Signal Path" --type single`) or through the admin UI. Both refuse to
overwrite an existing release and validate the generated draft.

### Featuring and performers (attribution)

Two optional structured fields sit alongside the free-string `credits` map
(which is what pages still print for songwriter/producer/etc.):

- `featuring` — an array of **artist ids** naming featured acts that have
  their own catalog presence (e.g. a PCBender single featuring `stab`).
  Allowed at the release level and inside `song`. The release/song page
  renders "feat. X" linking to `/artists/{id}/`.
- `performers` — an array inside `song` (per track) giving who played what.
  Each entry has a required `role`, an optional `note`, and **exactly one**
  of `member` (a member slug on the release's own `artist_id` band) or
  `artist` (an artist id). This data feeds the promoter pipeline; it is not
  rendered on the site yet.

```yaml
release:
  artist_id: pcbender
  featuring: [stab]
  song:
    performers:
      - artist: stab
        role: vocals
      - member: raven-cortez      # only valid when artist_id is that band
        role: guitar
```

`validate` resolves every `featuring` id and `performers[].artist` against
`content/artists/`, every `performers[].member` against the owning band's
`members`, and enforces unique member slugs.

## Legacy content

`content/clone/`, `content/pages/`, and `content/posts/` hold frozen
WordPress-migration output — a different, closed content model. See
[CONTENT-PIPELINE.md](CONTENT-PIPELINE.md); do not create new records there.
