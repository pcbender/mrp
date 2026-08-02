from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MappingPreset:
    name: str
    description: str
    scale_response: float
    motion_response: float
    onset_response: float
    opacity_response: float
    hue_response: float
    background_response: float
    visibility_bias: float
    role_gains: dict[str, float]
    # Energy lift for the two channels that used to decay from identity at
    # rest. Both are additive now: 0 means a trace sits at exactly the opacity
    # and saturation it was designed with and expresses energy through size,
    # line weight, hue, and beat flash instead. A preset opts back in to alpha
    # or saturation response by raising these, which can only ever add.
    opacity_lift: float = 0.0
    saturation_lift: float = 0.0
    # Line weight was already additive from identity, so this keeps its
    # historical strength; it lives here so every channel's amount has one
    # home that a component can override.
    line_width_lift: float = 1.4


@dataclass(frozen=True, slots=True)
class PalettePreset:
    name: str
    description: str
    colors: dict[str, str]


_UNITY_GAINS = {
    "master": 1.0,
    "drums": 1.0,
    "bass": 1.0,
    "vocals": 1.0,
    "instruments": 1.0,
}

MAPPING_PRESETS = {
    "balanced": MappingPreset(
        "balanced",
        "Measured motion with equal semantic-stem emphasis.",
        1.0,
        1.0,
        1.0,
        1.0,
        1.0,
        1.0,
        0.0,
        _UNITY_GAINS,
    ),
    "restrained": MappingPreset(
        "restrained",
        "Reduced motion, onset impulses, brightness, and layer density.",
        0.6,
        0.68,
        0.55,
        0.82,
        0.55,
        0.58,
        -0.08,
        _UNITY_GAINS,
    ),
    "kinetic": MappingPreset(
        "kinetic",
        "Expanded motion and rhythmic response while preserving topology.",
        1.35,
        1.38,
        1.45,
        1.08,
        1.35,
        1.25,
        0.08,
        _UNITY_GAINS,
        opacity_lift=0.25,
        saturation_lift=0.3,
    ),
    "vocal-focus": MappingPreset(
        "vocal-focus",
        "Centers vocal energy and softens supporting stem responses.",
        0.95,
        0.9,
        0.82,
        1.0,
        1.18,
        0.9,
        -0.02,
        {
            "master": 0.85,
            "drums": 0.72,
            "bass": 0.78,
            "vocals": 1.3,
            "instruments": 0.78,
        },
    ),
}

PALETTE_PRESETS = {
    "layer": PalettePreset(
        "layer",
        "Use the color declared on each visual layer.",
        {},
    ),
    "aurora": PalettePreset(
        "aurora",
        "Cool violet and cyan layers with a warm rhythmic accent.",
        {
            "master": "#6ee7f2",
            "drums": "#ffd166",
            "bass": "#4c78ff",
            "vocals": "#ff5fd2",
            "instruments": "#8c5cff",
        },
    ),
    "ember": PalettePreset(
        "ember",
        "Copper, crimson, amber, and warm rose.",
        {
            "master": "#ffb45c",
            "drums": "#ffe08a",
            "bass": "#c43d2f",
            "vocals": "#ff6b6b",
            "instruments": "#e8793e",
        },
    ),
    "ocean": PalettePreset(
        "ocean",
        "Deep blue, teal, sea-glass, and pale cyan.",
        {
            "master": "#7ee8e1",
            "drums": "#b8f2e6",
            "bass": "#2457c5",
            "vocals": "#47d7c8",
            "instruments": "#3a86c8",
        },
    ),
    "monochrome": PalettePreset(
        "monochrome",
        "Neutral silver layers with restrained tonal separation.",
        {
            "master": "#f0f0f0",
            "drums": "#ffffff",
            "bass": "#9a9a9a",
            "vocals": "#e0e0e0",
            "instruments": "#bdbdbd",
        },
    ),
}


def get_mapping_preset(name: str) -> MappingPreset:
    return MAPPING_PRESETS[name]


def get_palette_preset(name: str) -> PalettePreset:
    return PALETTE_PRESETS[name]


def preset_catalog() -> dict[str, list[dict[str, str]]]:
    return {
        "mapping": [
            {"name": preset.name, "description": preset.description}
            for preset in MAPPING_PRESETS.values()
        ],
        "palette": [
            {"name": preset.name, "description": preset.description}
            for preset in PALETTE_PRESETS.values()
        ],
    }
