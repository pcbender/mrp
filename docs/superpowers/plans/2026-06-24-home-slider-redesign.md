# Home Page Slider Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the dots ribbon and boxy arrow buttons from the two home page sliders, replace the arrows with bare elegant chevrons, and move each slide's title/artist caption from an on-image overlay to the open space below the image where the dots used to sit.

**Architecture:** All changes are confined to the shared `ImageLoop.astro` component's `variant="media"` styling/markup/script (the only variant the two home page carousels use), plus a one-line content change in `ArtistCarousel.astro`. Caption text is serialized into a `data-loop-items` JSON attribute on the carousel root; the existing client-side `show()` function (which already runs on every slide change) gains one block that updates the caption's text/link to match, mirroring how it already toggled the now-removed dots' active state.

**Tech Stack:** Astro 5.17 (`.astro` single-file components with TypeScript frontmatter + client `<script>`), plain CSS in `site/public/styles/global.css`. No component test framework exists in this repo for `.astro` files — verification is `npm run build` (catches template/TS errors) plus manual browser checks via `npm run dev`.

## Global Constraints

- Scope is `variant="media"` only. Do not modify the default `variant="split"` styling/behavior — it's unused today but kept for future use.
- Spec: `docs/superpowers/specs/2026-06-24-home-slider-redesign-design.md`.
- No automated tests exist for Astro components in this repo. Each task's "test" step is `npm run build` (from `/home/mrose/mrp/site`) plus a manual check in `npm run dev`, per this repo's established pattern (see `CLAUDE.md` UI-change guidance).
- Before any `git commit` in this plan, run `git branch --show-current` and confirm it prints `main` (or whatever branch you intentionally started this work on) before staging/committing — this repo directory can be shared with concurrent terminal activity.
- Commit only the files each task actually touches, by exact path — never `git add -A`.

---

## Task 1: Remove the dots ribbon

**Files:**
- Modify: `site/src/components/ImageLoop.astro`
- Modify: `site/public/styles/global.css`

**Interfaces:**
- Produces: `ImageLoop.astro` with no `.image-loop-dots` markup, no `dots` JS variable/update logic. `global.css` with no `.image-loop-dots*` rules. Later tasks build on this state.

- [ ] **Step 1: Remove the dots markup**

In `site/src/components/ImageLoop.astro`, find:

```astro
    <div class="image-loop-controls">
      <button class="icon-button" type="button" data-loop-prev aria-label={`Previous ${title}`}>‹</button>
      <div class="image-loop-dots" aria-hidden="true">
        {items.map((_, index) => <span class={index === 0 ? "is-active" : ""} data-loop-dot></span>)}
      </div>
      <button class="icon-button" type="button" data-loop-next aria-label={`Next ${title}`}>›</button>
    </div>
```

Replace with:

```astro
    <div class="image-loop-controls">
      <button class="icon-button" type="button" data-loop-prev aria-label={`Previous ${title}`}>‹</button>
      <button class="icon-button" type="button" data-loop-next aria-label={`Next ${title}`}>›</button>
    </div>
```

- [ ] **Step 2: Remove the dots JS**

In the same file's `<script>` block, find:

```ts
    const slides = Array.from(carousel.querySelectorAll<HTMLElement>("[data-loop-slide]"));
    const dots = Array.from(carousel.querySelectorAll<HTMLElement>("[data-loop-dot]"));
    const previous = carousel.querySelector<HTMLButtonElement>("[data-loop-prev]");
```

Replace with:

```ts
    const slides = Array.from(carousel.querySelectorAll<HTMLElement>("[data-loop-slide]"));
    const previous = carousel.querySelector<HTMLButtonElement>("[data-loop-prev]");
```

Then find:

```ts
      slides.forEach((slide, slideIndex) => {
        slide.setAttribute("aria-hidden", slideIndex === active ? "false" : "true");
      });
      dots.forEach((dot, dotIndex) => dot.classList.toggle("is-active", dotIndex === active));
    }
```

Replace with:

```ts
      slides.forEach((slide, slideIndex) => {
        slide.setAttribute("aria-hidden", slideIndex === active ? "false" : "true");
      });
    }
```

- [ ] **Step 3: Remove the dots CSS**

In `site/public/styles/global.css`, find this entire block (it sits between the `[data-loop-next]` grid-placement rule and `.artist-release-list`) and delete it completely, leaving a single blank line where it was:

```css
.image-loop-dots {
  display: flex;
  align-items: center;
  gap: 7px;
  max-width: min(340px, 42vw);
  overflow: hidden;
}

.image-loop-media .image-loop-dots {
  grid-column: 2;
  grid-row: 2;
  justify-content: center;
  max-width: min(620px, 80vw);
  margin: 0 auto;
}

.image-loop-dots span {
  width: 7px;
  height: 7px;
  flex: 0 0 auto;
  border-radius: 999px;
  background: var(--line);
}

.image-loop-media .image-loop-dots span {
  width: 8px;
  height: 8px;
  background: rgba(23, 23, 23, 0.26);
}

.image-loop-dots span.is-active {
  background: var(--red);
}
```

- [ ] **Step 4: Build check**

Run: `cd /home/mrose/mrp/site && npm run build`
Expected: build succeeds with no errors.

- [ ] **Step 5: Manual check**

Run: `cd /home/mrose/mrp/site && npm run dev`, open the home page in a browser.
Expected: both sliders show no dots below the image. Arrows (still the old boxy style) work and autoplay still cycles slides.

- [ ] **Step 6: Commit**

```bash
git branch --show-current
git add site/src/components/ImageLoop.astro site/public/styles/global.css
git commit -m "Remove dots ribbon from home page sliders"
```

---

## Task 2: Restyle arrows as bare chevrons

**Files:**
- Modify: `site/public/styles/global.css`

**Interfaces:**
- Consumes: nothing from Task 1 beyond the file existing in its post-Task-1 state.
- Produces: `.image-loop-media .icon-button` with no border/background, larger glyph, hover/focus color change. Later tasks don't depend on this.

- [ ] **Step 1: Restyle the media-variant icon button**

In `site/public/styles/global.css`, find:

```css
.image-loop-media .icon-button {
  width: 48px;
  height: 48px;
  border: 0;
  border-radius: 0;
  background: rgba(23, 23, 23, 0.48);
  color: #ffffff;
}
```

Replace with:

```css
.image-loop-media .icon-button {
  width: 48px;
  height: 48px;
  border: 0;
  border-radius: 0;
  background: transparent;
  color: var(--ink);
  font-size: 1.8rem;
  transition: color 150ms ease;
}

.image-loop-media .icon-button:hover,
.image-loop-media .icon-button:focus-visible {
  color: var(--red);
}
```

- [ ] **Step 2: Build check**

Run: `cd /home/mrose/mrp/site && npm run build`
Expected: build succeeds with no errors.

- [ ] **Step 3: Manual check**

Run: `cd /home/mrose/mrp/site && npm run dev`, open the home page.
Expected: both sliders' arrows are bare `‹`/`›` glyphs with no box/background, larger than before, and shift to the red accent color on hover/focus.

- [ ] **Step 4: Commit**

```bash
git branch --show-current
git add site/public/styles/global.css
git commit -m "Restyle home page slider arrows as bare chevrons"
```

---

## Task 3: Move the caption below the image

**Files:**
- Modify: `site/src/components/ImageLoop.astro`
- Modify: `site/public/styles/global.css`

**Interfaces:**
- Consumes: post-Task-1 state of `ImageLoop.astro` (no dots markup/JS) and `global.css` (no dots CSS).
- Produces: `isMedia`, `captionItems: { title; subtitle: string | null; href }[]`, `firstCaption` consts in the component frontmatter; a caption block in `.image-loop-controls` with `data-loop-caption` (the `<a>`), `data-loop-caption-title` (`<span>`), `data-loop-caption-subtitle` (`<span>`, toggles an `is-hidden` class); a `data-loop-items` JSON attribute on `[data-loop-carousel]`; a client-side `CaptionItem` interface and caption-sync block inside `show()`; new CSS classes `.image-loop-caption`, `.image-loop-caption-title`, `.image-loop-caption-subtitle`, `.image-loop-caption-subtitle.is-hidden`. Task 4 relies on `captionItems`' `subtitle` being `null` when the source item's `subtitle` is falsy.

- [ ] **Step 1: Compute caption data in the frontmatter**

In `site/src/components/ImageLoop.astro`, find:

```astro
const { eyebrow, title, ariaLabel, items, variant = "split" } = Astro.props;
---
```

Replace with:

```astro
const { eyebrow, title, ariaLabel, items, variant = "split" } = Astro.props;
const isMedia = variant === "media";
const captionItems = items.map((item) => ({ title: item.title, subtitle: item.subtitle ?? null, href: item.href }));
const firstCaption = captionItems[0];
---
```

- [ ] **Step 2: Serialize caption data onto the carousel root**

Find:

```astro
  <div class:list={["image-loop", variant === "media" && "image-loop-media"]} data-loop-carousel aria-label={ariaLabel}>
```

Replace with:

```astro
  <div
    class:list={["image-loop", variant === "media" && "image-loop-media"]}
    data-loop-carousel
    aria-label={ariaLabel}
    data-loop-items={isMedia ? JSON.stringify(captionItems) : undefined}
  >
```

- [ ] **Step 3: Stop rendering per-slide caption text for the media variant**

Find:

```astro
              <span class="card-kicker">{item.kicker}</span>
              <h3>{item.title}</h3>
              {item.subtitle && <p>{item.subtitle}</p>}
```

Replace with:

```astro
              {!isMedia && <span class="card-kicker">{item.kicker}</span>}
              {!isMedia && <h3>{item.title}</h3>}
              {!isMedia && item.subtitle && <p>{item.subtitle}</p>}
```

- [ ] **Step 4: Add the caption block between the arrows**

Find (this is the post-Task-1 state of this block):

```astro
    <div class="image-loop-controls">
      <button class="icon-button" type="button" data-loop-prev aria-label={`Previous ${title}`}>‹</button>
      <button class="icon-button" type="button" data-loop-next aria-label={`Next ${title}`}>›</button>
    </div>
```

Replace with:

```astro
    <div class="image-loop-controls">
      <button class="icon-button" type="button" data-loop-prev aria-label={`Previous ${title}`}>‹</button>
      {isMedia && firstCaption && (
        <a class="image-loop-caption" href={firstCaption.href} data-loop-caption>
          <span class="image-loop-caption-title" data-loop-caption-title>{firstCaption.title}</span>
          <span
            class:list={["image-loop-caption-subtitle", !firstCaption.subtitle && "is-hidden"]}
            data-loop-caption-subtitle
          >{firstCaption.subtitle ?? ""}</span>
        </a>
      )}
      <button class="icon-button" type="button" data-loop-next aria-label={`Next ${title}`}>›</button>
    </div>
```

Note: the subtitle `<span>` always renders (even when empty), toggling `is-hidden` instead of being conditionally omitted. This matters: the Our Artists slider has no subtitle on *any* slide (see Task 4), so if this span were conditionally omitted, the JS in Step 6 would never find it and would skip updating the caption entirely for that slider.

- [ ] **Step 5: Add the `CaptionItem` type to the client script**

In the same file's `<script>` block, find:

```ts
<script>
  const carousels = document.querySelectorAll<HTMLElement>("[data-loop-carousel]");

  carousels.forEach((carousel) => {
```

Replace with:

```ts
<script>
  interface CaptionItem {
    title: string;
    subtitle: string | null;
    href: string;
  }

  const carousels = document.querySelectorAll<HTMLElement>("[data-loop-carousel]");

  carousels.forEach((carousel) => {
```

- [ ] **Step 6: Wire up caption elements and sync them in `show()`**

Find:

```ts
    const slides = Array.from(carousel.querySelectorAll<HTMLElement>("[data-loop-slide]"));
    const previous = carousel.querySelector<HTMLButtonElement>("[data-loop-prev]");
    const next = carousel.querySelector<HTMLButtonElement>("[data-loop-next]");
    if (!track || slides.length === 0 || !previous || !next) return;

    let active = 0;
    let timer: number | undefined;

    function show(index: number) {
      active = (index + slides.length) % slides.length;
      track.style.transform = `translateX(-${active * 100}%)`;
      slides.forEach((slide, slideIndex) => {
        slide.setAttribute("aria-hidden", slideIndex === active ? "false" : "true");
      });
    }
```

Replace with:

```ts
    const slides = Array.from(carousel.querySelectorAll<HTMLElement>("[data-loop-slide]"));
    const previous = carousel.querySelector<HTMLButtonElement>("[data-loop-prev]");
    const next = carousel.querySelector<HTMLButtonElement>("[data-loop-next]");
    if (!track || slides.length === 0 || !previous || !next) return;

    const captionLink = carousel.querySelector<HTMLAnchorElement>("[data-loop-caption]");
    const captionTitle = carousel.querySelector<HTMLElement>("[data-loop-caption-title]");
    const captionSubtitle = carousel.querySelector<HTMLElement>("[data-loop-caption-subtitle]");
    const rawCaptionItems = carousel.dataset.loopItems;
    const captionItems: CaptionItem[] = rawCaptionItems ? JSON.parse(rawCaptionItems) : [];

    let active = 0;
    let timer: number | undefined;

    function show(index: number) {
      active = (index + slides.length) % slides.length;
      track.style.transform = `translateX(-${active * 100}%)`;
      slides.forEach((slide, slideIndex) => {
        slide.setAttribute("aria-hidden", slideIndex === active ? "false" : "true");
      });

      const captionItem = captionItems[active];
      if (captionLink && captionTitle && captionSubtitle && captionItem) {
        captionLink.href = captionItem.href;
        captionTitle.textContent = captionItem.title;
        captionSubtitle.textContent = captionItem.subtitle ?? "";
        captionSubtitle.classList.toggle("is-hidden", !captionItem.subtitle);
      }
    }
```

- [ ] **Step 7: Remove the now-dead media-variant overlay CSS**

In `site/public/styles/global.css`, find and delete this block (the kicker is no longer rendered at all in media-variant slides, so this override is unreachable):

```css
.image-loop-media .image-loop-slide .card-kicker {
  display: none;
}
```

Find and delete this block (the `<h3>` is no longer rendered inside media-variant slides at all, so the on-image overlay positioning is dead):

```css
.image-loop-media .image-loop-slide h3 {
  position: absolute;
  right: 24px;
  bottom: 20%;
  left: 24px;
  z-index: 1;
  color: #ffffff;
  text-shadow: 0 2px 10px rgba(0, 0, 0, 0.55);
  font-size: clamp(1.5rem, 3vw, 2.3rem);
  font-weight: 700;
  text-transform: uppercase;
}
```

Find and delete this block (the `<p>` is no longer rendered inside media-variant slides at all, so hiding it is unreachable):

```css
.image-loop-media .image-loop-slide p {
  display: none;
}
```

Each deletion leaves a single blank line where the block was — don't leave double-blank lines.

- [ ] **Step 8: Remove the matching dead mobile overrides**

In the `@media` breakpoint block near the end of the file, find and delete:

```css
  .image-loop-media .image-loop-slide h3 {
    right: 14px;
    bottom: 16%;
    left: 14px;
    font-size: clamp(1.15rem, 6vw, 1.6rem);
  }
```

And find and delete:

```css
  .image-loop-media .image-loop-slide .card-kicker,
  .image-loop-media .image-loop-slide p {
    display: none;
  }
```

Leave the neighboring `.image-loop-slide .card-kicker, .image-loop-slide h3, .image-loop-slide p { grid-column: 1; }` rule and the `.image-loop-controls { justify-content: space-between; }` rule untouched — both still apply (the first to the `"split"` variant, the second to both).

- [ ] **Step 9: Add the caption CSS**

In `site/public/styles/global.css`, add this new block immediately after the `.image-loop-dots`-block's former location (i.e. where Task 1 removed it, right after the `[data-loop-next]` grid-placement rule and before `.artist-release-list`):

```css
.image-loop-caption {
  display: grid;
  justify-items: center;
  gap: 4px;
  text-decoration: none;
  color: inherit;
}

.image-loop-media .image-loop-caption {
  grid-column: 2;
  grid-row: 2;
  max-width: min(620px, 80vw);
  margin: 0 auto;
}

.image-loop-caption-title {
  margin: 0;
  font-size: clamp(1.1rem, 2.4vw, 1.5rem);
  font-weight: 700;
  color: var(--ink);
}

.image-loop-caption-subtitle {
  margin: 0;
  font-size: 0.95rem;
  color: var(--muted);
}

.image-loop-caption-subtitle.is-hidden {
  display: none;
}
```

- [ ] **Step 10: Build check**

Run: `cd /home/mrose/mrp/site && npm run build`
Expected: build succeeds with no errors.

- [ ] **Step 11: Manual check**

Run: `cd /home/mrose/mrp/site && npm run dev`, open the home page.
Expected:
- Releases slider: caption below the image shows the release title (bold) above the artist name (smaller, muted), centered, outside the image's bordered/shadowed box.
- Our Artists slider: caption below the image shows the artist name (the subtitle line should not be visible — Task 4 makes this fully correct, but check it isn't showing the bio yet from the old per-slide `<p>`, since that's now suppressed by `!isMedia`).
- Clicking the caption text navigates to the release/artist page.
- Using the prev/next arrows and waiting for autoplay both update the caption in sync with the visible image.
- View the page source (or disable JS) and confirm slide 0's caption is present in the server-rendered HTML.

- [ ] **Step 12: Commit**

```bash
git branch --show-current
git add site/src/components/ImageLoop.astro site/public/styles/global.css
git commit -m "Move slider captions below the image, outside the frame"
```

---

## Task 4: Drop the artist bio from the Our Artists caption

**Files:**
- Modify: `site/src/components/ArtistCarousel.astro`

**Interfaces:**
- Consumes: `captionItems`/`firstCaption` behavior from Task 3, specifically that a `subtitle` of `undefined` becomes `null` in `captionItems` and hides the subtitle span via `is-hidden`.
- Produces: `ArtistCarousel.astro` passing no subtitle when `variant === "media"`.

- [ ] **Step 1: Make subtitle conditional on variant**

In `site/src/components/ArtistCarousel.astro`, find:

```astro
const { artists, variant = "split" } = Astro.props;
const items = artists.map((artist) => ({
  title: artist.name,
  subtitle: artist.summary,
  href: artist.href,
  image: artist.image,
  kicker: "Artist",
}));
```

Replace with:

```astro
const { artists, variant = "split" } = Astro.props;
const items = artists.map((artist) => ({
  title: artist.name,
  subtitle: variant === "media" ? undefined : artist.summary,
  href: artist.href,
  image: artist.image,
  kicker: "Artist",
}));
```

- [ ] **Step 2: Build check**

Run: `cd /home/mrose/mrp/site && npm run build`
Expected: build succeeds with no errors.

- [ ] **Step 3: Manual check**

Run: `cd /home/mrose/mrp/site && npm run dev`, open the home page.
Expected: Our Artists slider caption shows only the artist name — no bio text, on any slide (use the arrows to check several).

- [ ] **Step 4: Commit**

```bash
git branch --show-current
git add site/src/components/ArtistCarousel.astro
git commit -m "Show only the artist name in the Our Artists slider caption"
```

---

## Task 5: Full verification pass

**Files:** none (verification only).

- [ ] **Step 1: Desktop check**

Run: `cd /home/mrose/mrp/site && npm run dev`, open the home page at a desktop viewport width.
Verify, for both sliders:
- No dots are rendered anywhere.
- Arrows are bare chevrons with no box/border/background, and shift to the red accent on hover.
- Caption sits below the image, outside its bordered/shadowed frame.
- Releases: title above artist name. Our Artists: name only.
- Clicking a caption navigates correctly. Clicking arrows and waiting for autoplay both keep the caption in sync.

- [ ] **Step 2: Mobile check**

Using the browser's device toolbar (or resizing to ~375px wide), repeat the same checks. Confirm the caption text wraps/sits without overflowing, and the arrows remain tappable.

- [ ] **Step 3: Reduced-motion / pause-on-hover check**

Confirm autoplay still pauses on mouse hover and on keyboard focus within the slider, and resumes on mouseleave/blur (unchanged from before this work — this is a regression check, not a new behavior).

- [ ] **Step 4: No-JS fallback check**

View the page source (`curl -s http://127.0.0.1:4321/ | grep -A2 "image-loop-caption-title"` or browser "View Page Source") and confirm slide 0's title (and, for Releases, subtitle) is present in the raw server-rendered HTML for both sliders, not just inserted by JS.

No commit for this task — it's a verification gate. If anything fails, fix it as part of whichever task introduced the issue and re-commit there.
