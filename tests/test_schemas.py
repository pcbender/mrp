from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "mrp" / "schemas"
VALID = ROOT / "tests" / "fixtures" / "content" / "valid"
INVALID = ROOT / "tests" / "fixtures" / "content" / "invalid"


SCHEMA_FILES = {
    "site": "site.schema.json",
    "artist": "artist.schema.json",
    "release": "release.schema.json",
    "assets": "asset-manifest.schema.json",
    "validation_error": "validation-error.schema.json",
}


def load_yaml(path: Path):
    return yaml.safe_load(path.read_text())


def load_schema(name: str):
    return yaml.safe_load((SCHEMA_DIR / name).read_text())


def validator(schema_name: str) -> Draft202012Validator:
    return Draft202012Validator(load_schema(schema_name), format_checker=FormatChecker())


def error_record(file_path: Path, error) -> dict[str, str]:
    field = ".".join(str(part) for part in error.absolute_path) or "$"
    return {
        "file_path": str(file_path),
        "field": field,
        "severity": "error",
        "message": error.message,
    }


def test_schema_files_exist_and_are_valid():
    for schema_file in SCHEMA_FILES.values():
        schema = load_schema(schema_file)
        Draft202012Validator.check_schema(schema)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["title"]


def test_valid_content_samples_pass_validation():
    cases = [
        ("site.schema.json", VALID / "site.yaml"),
        ("artist.schema.json", VALID / "artist.yaml"),
        ("release.schema.json", VALID / "release-song.yaml"),
        ("release.schema.json", VALID / "release-album.yaml"),
        ("asset-manifest.schema.json", VALID / "assets.yaml"),
    ]

    for schema_name, sample_path in cases:
        errors = list(validator(schema_name).iter_errors(load_yaml(sample_path)))
        assert errors == [], f"{sample_path} failed validation: {errors}"


def test_invalid_release_samples_fail_validation():
    cases = [
        INVALID / "release-invalid-status.yaml",
        INVALID / "release-missing-required.yaml",
    ]

    for sample_path in cases:
        errors = list(validator("release.schema.json").iter_errors(load_yaml(sample_path)))
        assert errors, f"{sample_path} unexpectedly passed validation"


def test_validation_error_format_includes_required_fields():
    sample_path = INVALID / "release-invalid-status.yaml"
    error = next(validator("release.schema.json").iter_errors(load_yaml(sample_path)))
    record = error_record(sample_path, error)

    errors = list(validator("validation-error.schema.json").iter_errors(record))
    assert errors == []
    assert set(record) == {"file_path", "field", "severity", "message"}
