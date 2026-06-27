"""
Tags worker: zero-shot genre/mood/instrument classification via CLAP.
Optional — pipeline runs without it if torch/laion-clap are absent.

Model checkpoint (~300 MB) is downloaded once to ~/.cache/ on first run.

Usage:
    python -m critic.tags <audio_path> [--track-id <id>]
"""
from __future__ import annotations

import argparse
import io
import sys
import warnings
from pathlib import Path

from .record import Tags

_GENRES = [
    "rock", "folk rock", "blues rock", "classic rock", "indie rock",
    "pop rock", "country rock", "acoustic", "folk", "country", "blues",
    "pop", "electronic", "soul",
]
_MOODS = [
    "energetic", "melancholic", "uplifting", "introspective", "intense",
    "peaceful", "emotional", "nostalgic", "dark", "hopeful", "aggressive",
    "tender", "defiant",
]
_INSTRUMENTS = [
    "electric guitar", "acoustic guitar", "piano", "drums", "bass guitar",
    "lead vocals", "harmonica", "organ", "strings", "synthesizer",
    "background vocals", "mandolin",
]

_TOP_K = 3
_model = None


def _get_model():
    global _model
    if _model is None:
        import laion_clap
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            _sink = io.StringIO()
            _prev = sys.stdout
            sys.stdout = _sink
            try:
                _model = laion_clap.CLAP_Module(enable_fusion=False, amodel="HTSAT-tiny")
                _model.load_ckpt()
            finally:
                sys.stdout = _prev
    return _model


def _zero_shot(model, audio_path: str, candidates: list[str], prompt: str) -> list[str]:
    import torch
    import torch.nn.functional as F

    texts = [prompt.format(c) for c in candidates]

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with torch.no_grad():
            audio_embed = model.get_audio_embedding_from_filelist(
                [audio_path], use_tensor=True
            )
            text_embed = model.get_text_embedding(texts, use_tensor=True)

    audio_norm = F.normalize(audio_embed.float(), dim=-1)
    text_norm = F.normalize(text_embed.float(), dim=-1)
    sims = (audio_norm @ text_norm.T).squeeze(0)

    top_idx = sims.argsort(descending=True)[:_TOP_K].tolist()
    return [candidates[i] for i in top_idx]


def extract_tags(audio_path: str | Path) -> Tags:
    """
    Run CLAP zero-shot classification. Returns empty Tags if laion-clap
    or torch are not installed, or if classification fails.
    """
    try:
        model = _get_model()
    except Exception as exc:
        print(f"  ⚠  CLAP unavailable: {exc}")
        return Tags()

    path = str(audio_path)
    try:
        genres = _zero_shot(model, path, _GENRES, "this is a {} song")
        moods = _zero_shot(model, path, _MOODS, "this music feels {}")
        instruments = _zero_shot(model, path, _INSTRUMENTS, "this song features {}")
        return Tags(genre=genres, mood=moods, instruments=instruments)
    except Exception as exc:
        print(f"  ⚠  CLAP tagging failed: {exc}")
        return Tags()


def _main() -> None:
    parser = argparse.ArgumentParser(description="MRP Critic — CLAP tags worker")
    parser.add_argument("path", help="Audio file (WAV preferred)")
    parser.add_argument("--track-id")
    args = parser.parse_args()

    path = Path(args.path)
    # If given a proxy, resolve to master via ingest
    if path.suffix == ".opus":
        print("Pass the WAV master, not the proxy, for best CLAP results.")
        return

    print(f"Loading CLAP model (downloads ~300 MB on first run)…")
    tags = extract_tags(path)

    if not any([tags.genre, tags.mood, tags.instruments]):
        print("No tags returned.")
    else:
        print(f"\nGenre      : {tags.genre}")
        print(f"Mood       : {tags.mood}")
        print(f"Instruments: {tags.instruments}")


if __name__ == "__main__":
    _main()
