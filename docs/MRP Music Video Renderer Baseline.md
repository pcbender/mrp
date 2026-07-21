# MRP Music Video Renderer Baseline

This record freezes the proven Spirophonic Python renderer state used for the
Milestone 2 transplant. It is provenance and parity evidence, not a dependency
on the Spirophonic repository at runtime.

## Source provenance

- Captured: 2026-07-20
- Source checkout: `/home/mrose/spirophonic`
- Source branch: `feat/visual-redesign`
- Source commit: `e3d4b100e026d486ce2c28547e6e8a907b1c621a`
- Source worktree: clean before and after baseline verification
- Python: 3.12.3
- Package version: 0.1.0

The transplant copied only the headless Python renderer, its Python tests, and
its geometry golden fixture. The Spirophonic React application, Node packages,
and generated build outputs were not copied or modified.

## Passing source suite

Numba's cache was redirected because the source checkout was intentionally
read-only during verification:

```bash
NUMBA_CACHE_DIR=/tmp/spirophonic-numba-cache \
  PYTHONDONTWRITEBYTECODE=1 \
  .venv/bin/pytest -q -p no:cacheprovider
```

Result: `69 passed in 18.88s`.

## Locked direct dependencies

| Package | Proven version | MRP installation |
| --- | ---: | --- |
| librosa | 0.11.0 | `requirements-video.txt` |
| numpy | 2.4.6 | `requirements-video.txt` |
| opencv-python-headless | 4.13.0.92 | `requirements-video.txt` |
| Pillow | 12.3.0 | `requirements-video.txt` |
| pydantic | 2.13.4 | `requirements-video.txt` |
| PyYAML | 6.0.3 | `requirements-video.txt` |
| rich | 14.3.4 | `requirements-video.txt` |
| soundfile | 0.14.0 | `requirements-video.txt` |
| typer | 0.27.0 | `requirements-video.txt` |
| openai | 2.46.0 | optional `requirements-video-align.txt` |

`requirements-video.txt` also pins the complete transitive dependency closure
from this environment; the table highlights the renderer's direct packages.

The normal renderer suite requires no OpenAI import, credentials, or network
access. OpenAI remains a lazy, alignment-only dependency.

## FFmpeg baseline

- `ffmpeg`: 6.1.1-3ubuntu5
- `ffprobe`: 6.1.1-3ubuntu5
- Required encoder path: H.264 (`libx264`) video plus AAC audio
- Verification contract: progressive `yuv420p`, square pixels, faststart,
  configured dimensions/frame rate, AAC-LC stereo 48 kHz audio, no unexpected
  streams, and duration within tolerance

## Representative parity artifacts

These source-relative hashes identify the last known production-scale render
without copying generated media into MRP:

| Source-relative artifact | SHA-256 |
| --- | --- |
| `build/you-dont-say/project.yaml` | `db9850e6a5fbbea8f47e7646c3e033588c0e6297d22ef3eeeb34863869a375b0` |
| `build/you-dont-say/you-dont-say-visual-redesign.render.json` | `0e00524138faedd93c7da783a20f23d9f2442f50bd5abb5a08c45fc6668ca5cd` |
| `build/you-dont-say/you-dont-say-visual-redesign.mp4` | `e94c8077dd133a1d317035ec97ca171f31d90d1c92f85cf7f246c8623151ebb7` |
| `build/you-dont-say/stills/final-contact-sheet.jpg` | `92c85226ed750741a71ac824be7e69d97cb561ab54fa5bbd17ae2d23a0103e74` |
| `tests/fixtures/trochoid-golden.json` | `92e210c450cc5735a6981f14cf74750a7b98dd6079484d92f700460906f827bb` |

The representative render manifest reports 12,250 frames at 1920x1080 and
30 fps, a 408.333333-second verified output, H.264/yuv420p video, and AAC-LC
stereo 48 kHz audio. Its verification result is valid.

## MRP transplant rule

The initial move is namespace-only: implementation behavior, exception class
names, the `spirophonic-frame-sequence` interchange identifier, and golden
geometry values remain stable for parity. User-facing command guidance points
to `scripts/mrp video ...`. Any semantic rename or renderer cleanup belongs
after MRP parity is established.
