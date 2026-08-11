"""
promoter CLI

Commands:
    promoter blurb --artist <slug> [--releases N] [--model dev|default] [--dry-run]
    promoter bio   --artist <slug> [--model dev|default] [--dry-run]
    promoter keywords --artist <slug> [--model dev|default] [--dry-run]
    promoter kit   --release <slug> [--model dev|default] [--out <path>]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import MODEL_DEFAULT, model_for
from .gather import (
    get_all_lyrics,
    get_artist,
    get_catalog,
    get_critic_text,
    get_recent_releases,
    get_release,
)
from .generate import generate_bio, generate_blurb, generate_keywords, generate_kit
from .keywords import KEYWORD_BUDGET, keyword_field, merge_keywords, normalize
from .writeback import write_bio, write_keywords, write_promo_blurb


def cmd_blurb(args: argparse.Namespace) -> None:
    artist = get_artist(args.artist)
    if not artist:
        print(f"  ✗  Artist '{args.artist}' not found", file=sys.stderr)
        sys.exit(1)

    artist_name = artist.get("name", args.artist)
    bio_short = artist.get("bio_short") or artist.get("bio_long") or ""

    print(f"  artist : {artist_name}")
    print(f"  fetching {args.releases} most recent release(s)…")
    releases = get_recent_releases(args.artist, n=args.releases)

    if not releases:
        print("  ⚠  No releases found for this artist.", file=sys.stderr)
        sys.exit(1)

    release_inputs = []
    for rel in releases:
        print(f"    {rel['title']} ({rel['release_date']})  — fetching critic text…")
        review_text = get_critic_text(rel["slug"], args.artist)
        release_inputs.append({**rel, "review_text": review_text})

    model = model_for(args.model)
    print(f"  calling {model}…")
    blurb = generate_blurb(artist_name, bio_short, release_inputs, model=model)

    print("\n── promo_blurb ──────────────────────────────────────")
    print(blurb)
    print("─────────────────────────────────────────────────────\n")

    if args.dry_run:
        print("  (dry-run — not written)")
        return

    path = write_promo_blurb(args.artist, blurb)
    print(f"  ✓  Written to {path}")


def cmd_bio(args: argparse.Namespace) -> None:
    artist = get_artist(args.artist)
    if not artist:
        print(f"  ✗  Artist '{args.artist}' not found", file=sys.stderr)
        sys.exit(1)

    artist_name = artist.get("name", args.artist)
    existing_short = artist.get("bio_short", "")
    existing_long = artist.get("bio_long", "")

    if (existing_short or existing_long) and not args.force:
        print(
            f"  ✗  {artist_name} already has a bio. Use --force to overwrite.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"  artist : {artist_name}")
    print("  gathering lyrics…")
    lyrics = get_all_lyrics(args.artist)

    if not lyrics:
        print("  ⚠  No lyrics found — bio will be minimal.", file=sys.stderr)

    print(f"  found {len(lyrics)} lyric track(s)")
    model = model_for(args.model)
    print(f"  calling {model}…")

    bio_short, bio_long = generate_bio(
        artist_name,
        artist.get("type", "solo"),
        lyrics,
        model=model,
    )

    print("\n── bio_short ─────────────────────────────────────────")
    print(bio_short)
    print("\n── bio_long ──────────────────────────────────────────")
    print(bio_long)
    print("─────────────────────────────────────────────────────\n")
    print("  ⚠  bio_auto_generated=true — review before publishing")

    if args.dry_run:
        print("  (dry-run — not written)")
        return

    path = write_bio(args.artist, bio_short, bio_long)
    print(f"  ✓  Written to {path}")


def cmd_keywords(args: argparse.Namespace) -> None:
    artist = get_artist(args.artist)
    if not artist:
        print(f"  ✗  Artist '{args.artist}' not found", file=sys.stderr)
        sys.exit(1)

    artist_name = artist.get("name", args.artist)
    existing = normalize(artist.get("keywords") or [])
    patterns = artist.get("keywords_blocked") or []

    print(f"  artist : {artist_name}")
    print(f"  existing: {len(existing)} keyword(s), {len(keyword_field(existing))}/{KEYWORD_BUDGET} chars")
    if patterns:
        print(f"  blocklist: {len(patterns)} line(s)")
    releases = get_catalog(args.artist)
    print(f"  catalog : {len(releases)} release(s)")

    model = model_for(args.model)
    print(f"  calling {model}…")
    candidates = generate_keywords(artist, releases, existing, model=model)

    kept, dropped, blocked = merge_keywords(existing, candidates, patterns)
    added = [k for k in kept if k not in existing]

    print("\n── keywords ──────────────────────────────────────────")
    print(keyword_field(kept))
    print("─────────────────────────────────────────────────────")
    print(f"  {len(kept)} keyword(s), {len(keyword_field(kept))}/{KEYWORD_BUDGET} chars")
    print(f"  +{len(added)} new: {', '.join(added) if added else '(none)'}")
    if blocked:
        print(f"  ·  {len(blocked)} blocked by the blocklist: {', '.join(blocked)}")
    if dropped:
        print(f"  ⚠  {len(dropped)} did not fit the budget: {', '.join(dropped)}")
        print("     Prune the list on the artist page to make room.")
    print("  ⚠  keywords_auto_generated=true — review before publishing")

    if args.dry_run:
        print("  (dry-run — not written)")
        return

    if kept == existing:
        print("  ·  Nothing new to add — record unchanged.")
        return

    path = write_keywords(args.artist, kept)
    print(f"  ✓  Written to {path}")


def cmd_kit(args: argparse.Namespace) -> None:
    release = get_release(args.release)
    if not release:
        print(f"  ✗  Release '{args.release}' not found", file=sys.stderr)
        sys.exit(1)
    artist_id = release.get("artist_id", "")
    artist = get_artist(artist_id)
    if not artist:
        print(f"  ✗  Artist '{artist_id}' not found", file=sys.stderr)
        sys.exit(1)

    print(f"  release: {release.get('title', args.release)}")
    print(f"  artist : {artist.get('name', artist_id)}")
    review_text = get_critic_text(args.release, artist_id)
    print(f"  critic text: {'yes' if review_text else 'none'}")

    model = model_for(args.model)
    print(f"  calling {model}…")
    kit = generate_kit(artist, release, review_text, model=model)
    kit["_meta"] = {"release": args.release, "artist_id": artist_id, "model": model}

    payload = json.dumps(kit, indent=2, ensure_ascii=False)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(payload)
        print(f"  ✓  Written to {out_path}")
    else:
        print(payload)


def main() -> None:
    parser = argparse.ArgumentParser(prog="promoter", description="MRP Promoter")
    sub = parser.add_subparsers(dest="command", required=True)

    # blurb
    p_blurb = sub.add_parser("blurb", help="Generate promo_blurb from recent releases")
    p_blurb.add_argument("--artist", required=True)
    p_blurb.add_argument("--releases", type=int, default=3)
    p_blurb.add_argument("--model", default="default", choices=["dev", "default"])
    p_blurb.add_argument("--dry-run", action="store_true")

    # bio
    p_bio = sub.add_parser("bio", help="Bootstrap bio_short + bio_long from lyrics")
    p_bio.add_argument("--artist", required=True)
    p_bio.add_argument("--model", default="default", choices=["dev", "default"])
    p_bio.add_argument("--force", action="store_true", help="Overwrite existing bio")
    p_bio.add_argument("--dry-run", action="store_true")

    # keywords
    p_kw = sub.add_parser("keywords", help="Append YouTube channel keywords from the catalog")
    p_kw.add_argument("--artist", required=True)
    p_kw.add_argument("--model", default="default", choices=["dev", "default"])
    p_kw.add_argument("--dry-run", action="store_true")

    # kit
    p_kit = sub.add_parser("kit", help="Generate per-platform promo copy for a release")
    p_kit.add_argument("--release", required=True)
    p_kit.add_argument("--model", default="default", choices=["dev", "default"])
    p_kit.add_argument("--out", default="", help="Write kit JSON here instead of stdout")

    args = parser.parse_args()
    if args.command == "blurb":
        cmd_blurb(args)
    elif args.command == "bio":
        cmd_bio(args)
    elif args.command == "keywords":
        cmd_keywords(args)
    elif args.command == "kit":
        cmd_kit(args)


if __name__ == "__main__":
    main()
