"""
promoter CLI

Commands:
    promoter blurb --artist <slug> [--releases N] [--model dev|default] [--dry-run]
    promoter bio   --artist <slug> [--model dev|default] [--dry-run]
"""
from __future__ import annotations

import argparse
import sys

from .config import MODEL_DEFAULT, model_for
from .gather import get_all_lyrics, get_artist, get_critic_text, get_recent_releases
from .generate import generate_bio, generate_blurb
from .writeback import write_bio, write_promo_blurb


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

    args = parser.parse_args()
    if args.command == "blurb":
        cmd_blurb(args)
    elif args.command == "bio":
        cmd_bio(args)


if __name__ == "__main__":
    main()
