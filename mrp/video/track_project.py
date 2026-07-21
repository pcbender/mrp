"""Lightweight versioned envelope for one MRP track video project."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from mrp.video.project import ContractModel, ProjectManifest

ADAPTER_VERSION = 1
RENDERER_CONTRACT_VERSION = 1
SOURCE_RENDERER_REVISION = "e3d4b100e026d486ce2c28547e6e8a907b1c621a"


class TrackSource(ContractModel):
    release: Path
    track_slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    track_key: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*--[a-z0-9][a-z0-9-]*$")
    artist_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")

    @model_validator(mode="after")
    def release_is_repo_relative(self) -> "TrackSource":
        if self.release.is_absolute() or self.release.parts[:2] != (
            "content",
            "releases",
        ):
            raise ValueError("release must be relative below content/releases")
        return self


class TrackProjectDocument(ContractModel):
    version: Literal[1] = 1
    adapter_version: Literal[1] = ADAPTER_VERSION
    renderer_contract_version: Literal[1] = RENDERER_CONTRACT_VERSION
    source_renderer_revision: str = SOURCE_RENDERER_REVISION
    source: TrackSource
    project: ProjectManifest
