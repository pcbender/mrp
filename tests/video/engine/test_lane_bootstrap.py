from pathlib import Path


def test_engine_lane_is_ready_for_isolated_renderer_tests():
    """Keep the renderer-only command green before the engine moves in M2."""
    lane = Path(__file__).resolve().parent

    assert lane.name == "engine"
    assert lane.parent.name == "video"
