# Home page slider redesign

## Background

The home page (`site/src/pages/index.astro`) has two sliders, both built from the
shared `ImageLoop.astro` component via `ReleaseCarousel.astro` and
`ArtistCarousel.astro`, both using `variant="media"`. Today each slide overlays
its title in bold white text directly on the image, with a row of dots and two
boxy `‹`/`›` buttons below the image for navigation.

`variant="media"` is used in exactly these two places — confirmed via repo
search, no other page references it. The default `variant="split"` (image +
text side-by-side) is unused today but kept for potential future use, and is
out of scope for this change.

## Goals

- Remove the dots ribbon entirely.
- Replace the boxy arrow buttons with a more elegant, minimal chevron.
- Move each slide's caption text off the image and into the space below it,
  where the dots used to sit — outside the image's bordered/shadowed frame.
- Releases slider caption: release title (prominent) above artist name
  (smaller, muted).
- Our Artists slider caption: artist name only (no bio blurb).

## Non-goals

- No changes to the `"split"` variant or any page that might use it later.
- No changes to autoplay timing, pause-on-hover/focus, or reduced-motion
  behavior — only the caption/arrows/dots presentation changes.
- No changes to `ReleaseCarousel.astro`'s data shape (title/subtitle order
  already matches the desired caption order).

## Design

### Arrows

`.image-loop-media .icon-button` drops its border, background fill, and boxed
shape. It becomes a bare `‹`/`›` glyph: larger font-size, `color: var(--ink)`,
transparent background, with a hover/focus color shift (e.g. to
`var(--red)`) for affordance. Position is unchanged — still beside the image,
vertically centered, in the existing 52px grid columns.

### Dots removal

The dots ribbon is deleted outright, not just hidden:

- Markup: the `.image-loop-dots` div and its `<span data-loop-dot>` children
  are removed from `ImageLoop.astro`.
- Script: the `dots` query, and the `dots.forEach(...)` active-class toggle
  inside `show()`, are removed.
- CSS: all `.image-loop-dots*` rules in `global.css` are deleted.

Since dots aren't used by any other variant or page today, this is a full
removal rather than a variant-scoped hide.

### Caption placement

A new caption element is inserted into the same grid slot the dots occupied:
`grid-column: 2; grid-row: 2` within `.image-loop-media`, between the two
arrow buttons, outside the image's bordered/shadowed viewport box. The image
card itself (border, shadow, sizing) is untouched.

The caption is only rendered/shown for `variant === "media"`; for the
`"split"` variant this block stays absent (split already shows title/subtitle
inline next to the image via the per-slide markup, unchanged by this work).

### Data flow: keeping a no-JS fallback

The carousel's slide transitions already depend on JS (`show()` sets
`transform` and `aria-hidden`), so there's already a hard JS dependency for
interactivity. But today, *without* JS, the first slide's title is still
visible (it's server-rendered, just absolutely positioned via CSS) — that
resilience is worth preserving for the new caption.

Approach:

1. `ImageLoop.astro` serializes the slide data needed for the caption
   (`title`, `subtitle`, `href`) into a `data-loop-items` JSON attribute on
   the carousel root (`[data-loop-carousel]`), for `variant === "media"` only.
2. The caption markup is server-rendered using `items[0]` by default, so the
   first slide's caption is visible with no JS — mirroring how dot 0 was
   always pre-rendered `is-active` today.
3. The client `show(index)` function gains one step: alongside the existing
   `transform`/`aria-hidden` updates, it parses `data-loop-items` once and on
   each call updates the caption's title text, subtitle text (toggling
   visibility if absent), and the wrapping `<a href>` to match the active
   slide.

For `variant === "media"`, the per-slide `<h3>`/`<p>`/`<span class="card-kicker">`
inside each slide's `<a>` stop rendering (made conditional on
`variant !== "media"`), since that text now lives solely in the shared
caption. This avoids hidden/duplicate text nodes per slide.

### Content per slider

- **Releases** (`ReleaseCarousel.astro`): no changes needed. `items` already
  maps `title: release.title, subtitle: release.artistName` — title-first
  ordering matches the desired caption order directly.
- **Our Artists** (`ArtistCarousel.astro`): one-line change. `subtitle` is
  only set to `artist.summary` when `variant !== "media"`:
  ```
  subtitle: variant === "media" ? undefined : artist.summary
  ```
  so the bio blurb doesn't appear in the media-variant caption, while a
  future `"split"` usage would still get the full subtitle.

### Caption styling

New CSS, scoped under `.image-loop-media`:

- Caption wrapper: centered text, max-width matching the old dots row (so it
  doesn't overflow the slider's footprint on wide screens).
- Title: bold, prominent, but not as large as the old image-overlay
  treatment (no text-shadow needed now that it's not sitting on top of the
  image) — sized similarly to other card titles on the site (see
  `ArtistCard.astro`'s plain `<h3>`/`<p>` convention).
- Subtitle (artist name on Releases): smaller, `color: var(--muted)`,
  consistent with `.image-loop-slide p` elsewhere in this file.

### Cleanup

The now-dead absolute-overlay CSS for `.image-loop-media .image-loop-slide h3`
(both the base rule and its mobile breakpoint override around line 1567) is
removed rather than left disabled, since media-variant slides no longer
render `<h3>` at all.

## Files touched

- `site/src/components/ImageLoop.astro` — markup + script changes described
  above.
- `site/src/components/ArtistCarousel.astro` — one-line subtitle conditional.
- `site/public/styles/global.css` — remove dot rules + dead overlay rules,
  restyle `.image-loop-media .icon-button`, add caption rules.

No changes to `site/src/pages/index.astro`, `ReleaseCarousel.astro`, or any
content/data files.

## Verification

Manual check in a dev server, both sliders, at desktop and mobile widths:

- No dots are rendered; arrows show as bare chevrons with no box.
- Releases slider caption shows Title above Artist name, centered below the
  image, outside its frame; clicking the caption navigates to the release.
- Our Artists slider caption shows only the artist name.
- Manual prev/next clicks and autoplay both update the caption in sync with
  the visible slide.
- Disabling JS (or viewing the raw server-rendered HTML) still shows slide 0's
  caption.
- Reduced-motion/autoplay/pause-on-hover behavior is unchanged from today.
