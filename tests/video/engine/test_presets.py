import json

import numpy as np
from typer.testing import CliRunner

from mrp.video.cli import app
from mrp.video.presets import preset_catalog
from mrp.video.renderer import build_render_context, render_frame
from tests.video.engine.test_choreography import _aligned_sections, _analysis_bundle
from tests.video.engine.test_renderer import FONT_PATH, _project

runner = CliRunner()


def _preset_context(mapping: str, palette: str, custom: list[str] | None = None):
    project = _project()
    visuals = project.visuals.model_copy(
        update={
            "mapping_preset": mapping,
            "palette_preset": palette,
            "palette": custom or [],
        }
    )
    project = project.model_copy(update={"visuals": visuals})
    return build_render_context(
        project,
        _analysis_bundle(),
        _aligned_sections(),
        root=FONT_PATH.parent,
    )


def test_preset_catalog_is_stable_and_available_from_cli() -> None:
    catalog = preset_catalog()

    assert [item["name"] for item in catalog["mapping"]] == [
        "balanced",
        "restrained",
        "kinetic",
        "vocal-focus",
    ]
    assert [item["name"] for item in catalog["palette"]] == [
        "layer",
        "aurora",
        "ember",
        "ocean",
        "monochrome",
    ]
    result = runner.invoke(app, ["presets", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.stdout) == catalog


def test_mapping_and_palette_presets_are_deterministic_and_distinct() -> None:
    balanced = render_frame(
        _preset_context("balanced", "layer"),
        4.5,
        45,
        width=320,
        height=180,
    )
    restrained = render_frame(
        _preset_context("restrained", "ocean"),
        4.5,
        45,
        width=320,
        height=180,
    )
    kinetic = render_frame(
        _preset_context("kinetic", "ember"),
        4.5,
        45,
        width=320,
        height=180,
    )
    kinetic_again = render_frame(
        _preset_context("kinetic", "ember"),
        4.5,
        45,
        width=320,
        height=180,
    )

    assert not np.array_equal(balanced, restrained)
    assert not np.array_equal(balanced, kinetic)
    np.testing.assert_array_equal(kinetic, kinetic_again)

    custom = render_frame(
        _preset_context("balanced", "ember", ["#00ff00"]),
        4.5,
        45,
        width=320,
        height=180,
    )
    assert not np.array_equal(custom, kinetic)
