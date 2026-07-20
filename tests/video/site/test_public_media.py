from pathlib import Path

import pytest

from mrp.core.public_media import (
    PublicMediaError,
    local_media_relative,
    public_media_root,
)


def test_public_media_root_must_be_outside_repo_and_not_filesystem_root(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    monkeypatch.setenv("MRP_PUBLIC_MEDIA_ROOT", str(repo / "media"))
    with pytest.raises(PublicMediaError, match="inside repository"):
        public_media_root(repo)

    monkeypatch.setenv("MRP_PUBLIC_MEDIA_ROOT", "/")
    with pytest.raises(PublicMediaError, match="filesystem root"):
        public_media_root(repo)


def test_local_public_media_reference_rejects_escape_and_accepts_https() -> None:
    with pytest.raises(PublicMediaError, match="unsafe"):
        local_media_relative("/media/../private/video.mp4")
    with pytest.raises(PublicMediaError, match="begin with /media/"):
        local_media_relative("/assets/processed/video.mp4")

    assert local_media_relative("https://cdn.example/video.mp4") is None
    assert local_media_relative("/media/music-videos/track/video.mp4") == Path(
        "music-videos/track/video.mp4"
    )
