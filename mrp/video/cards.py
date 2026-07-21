from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageOps, UnidentifiedImageError

from mrp.video.project import CardConfig


@dataclass(frozen=True, slots=True)
class PreparedCards:
    opening: NDArray[np.uint8]
    closing: NDArray[np.uint8]


class SpirophonicCardError(Exception):
    pass


def validate_card_image(source_path: Path) -> None:
    try:
        with Image.open(source_path) as source:
            source.verify()
    except (OSError, UnidentifiedImageError) as exc:
        raise SpirophonicCardError(
            f"cannot load card image {source_path}: {exc}"
        ) from exc


def _parse_hex_color(value: str) -> tuple[int, int, int]:
    return tuple(int(value[index : index + 2], 16) for index in (1, 3, 5))


def render_card(
    config: CardConfig,
    source_path: Path,
    *,
    width: int,
    height: int,
) -> NDArray[np.uint8]:
    """Fit a still card to one RGB frame without changing its aspect ratio."""
    try:
        with Image.open(source_path) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
    except (OSError, UnidentifiedImageError) as exc:
        raise SpirophonicCardError(
            f"cannot load card image {source_path}: {exc}"
        ) from exc

    target_size = (width, height)
    if config.fit == "cover":
        fitted = ImageOps.fit(
            image,
            target_size,
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        )
    else:
        contained = ImageOps.contain(
            image,
            target_size,
            method=Image.Resampling.LANCZOS,
        )
        fitted = Image.new("RGB", target_size, _parse_hex_color(config.background))
        x = (width - contained.width) // 2
        y = (height - contained.height) // 2
        fitted.paste(contained, (x, y))
    return np.asarray(fitted, dtype=np.uint8)


def prepare_cards(
    opening_config: CardConfig,
    closing_config: CardConfig,
    *,
    opening_path: Path,
    closing_path: Path,
    width: int,
    height: int,
) -> PreparedCards:
    return PreparedCards(
        opening=render_card(
            opening_config,
            opening_path,
            width=width,
            height=height,
        ),
        closing=render_card(
            closing_config,
            closing_path,
            width=width,
            height=height,
        ),
    )


def blend_frames(
    base: NDArray[np.uint8],
    overlay: NDArray[np.uint8],
    amount: float,
) -> NDArray[np.uint8]:
    if base.shape != overlay.shape:
        raise SpirophonicCardError("crossfade frames must have identical dimensions")
    amount = min(1, max(0, amount))
    blended = base.astype(np.float32) * (1 - amount)
    blended += overlay.astype(np.float32) * amount
    return np.rint(blended).astype(np.uint8)
