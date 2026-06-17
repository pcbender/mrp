from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from mrp.core.approve import approve, format_approval
from mrp.core.build import build_repository, format_build
from mrp.core.deploy import format_deployment, stage_build
from mrp.core.import_site import DEFAULT_SOURCE, format_import, import_site
from mrp.core.inspect import format_inspection, inspect_repository
from mrp.core.publish import format_publish, publish
from mrp.core.release import create_release, format_release_create
from mrp.core.rollback import format_rollback, rollback
from mrp.core.status import format_status, status
from mrp.core.validate import format_validation, validate_repository
from mrp.core.verify import format_verification, verify_target


EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_CONFIG = 2
EXIT_UNSAFE = 3
EXIT_DEPLOYMENT = 4
EXIT_RUNTIME = 5

PLACEHOLDER_COMMANDS = {"init"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mrp",
        description="Maricopa Release Publisher",
    )
    add_global_options(parser)

    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="Inspect repository state.")
    add_global_options(inspect_parser, suppress_defaults=True)

    validate_parser = subparsers.add_parser("validate", help="Validate content records.")
    add_global_options(validate_parser, suppress_defaults=True)
    add_common_command_options(validate_parser, "validate")

    build_command_parser = subparsers.add_parser("build", help="Build the static site.")
    add_global_options(build_command_parser, suppress_defaults=True)
    add_common_command_options(build_command_parser, "build")

    stage_parser = subparsers.add_parser("stage", help="Deploy a build to a local staging target.")
    add_global_options(stage_parser, suppress_defaults=True)
    add_common_command_options(stage_parser, "stage")

    verify_parser = subparsers.add_parser("verify", help="Verify a local deployed target.")
    add_global_options(verify_parser, suppress_defaults=True)
    add_common_command_options(verify_parser, "verify")

    approve_parser = subparsers.add_parser("approve", help="Approve a verified build or release.")
    add_global_options(approve_parser, suppress_defaults=True)
    add_common_command_options(approve_parser, "approve")

    status_parser = subparsers.add_parser("status", help="Show publishing status.")
    add_global_options(status_parser, suppress_defaults=True)
    add_common_command_options(status_parser, "status")

    publish_parser = subparsers.add_parser("publish", help="Publish an approved build to local production.")
    add_global_options(publish_parser, suppress_defaults=True)
    add_common_command_options(publish_parser, "publish")

    rollback_parser = subparsers.add_parser("rollback", help="Rollback local production.")
    add_global_options(rollback_parser, suppress_defaults=True)
    add_common_command_options(rollback_parser, "rollback")

    for command in sorted(PLACEHOLDER_COMMANDS):
        command_parser = subparsers.add_parser(command, help=f"{command} command placeholder.")
        add_global_options(command_parser, suppress_defaults=True)
        add_common_command_options(command_parser, command)

    release_parser = subparsers.add_parser("release", help="Release record commands.")
    add_global_options(release_parser, suppress_defaults=True)
    release_subparsers = release_parser.add_subparsers(dest="release_command", required=True)
    create_parser = release_subparsers.add_parser("create", help="Create a release manifest.")
    add_global_options(create_parser, suppress_defaults=True)
    create_parser.add_argument("--artist")
    create_parser.add_argument("--title")
    create_parser.add_argument("--type", choices=["single", "ep", "album"])

    import_parser = subparsers.add_parser("import-site", help="Import source site content.")
    add_global_options(import_parser, suppress_defaults=True)
    import_parser.add_argument("--source", default=str(DEFAULT_SOURCE))
    add_common_command_options(import_parser, "import-site")

    return parser


def add_global_options(parser: argparse.ArgumentParser, suppress_defaults: bool = False) -> None:
    default = argparse.SUPPRESS if suppress_defaults else None
    parser.add_argument(
        "--json",
        action="store_true",
        default=default,
        help="Emit machine-readable JSON.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=default,
        help="Plan without writing changes.",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        default=default,
        help="Disable terminal color.",
    )
    parser.add_argument(
        "--repo",
        default=argparse.SUPPRESS if suppress_defaults else ".",
        help="Repository root to operate on.",
    )


def add_common_command_options(parser: argparse.ArgumentParser, command: str) -> None:
    if command in {"validate", "build", "verify", "approve", "publish", "status"}:
        parser.add_argument("--release")
    if command in {"stage", "verify", "publish"}:
        parser.add_argument("--target")
    if command in {"stage", "approve", "publish", "rollback"}:
        parser.add_argument("--build")
    if command == "build":
        parser.add_argument("--skip-validate", action="store_true")
    if command == "publish":
        parser.add_argument("--auto-approve", action="store_true")
    if command == "rollback":
        parser.add_argument("--to")
        parser.add_argument("--yes", action="store_true")


def placeholder_result(args: argparse.Namespace) -> dict[str, Any]:
    command = args.command
    if command == "release":
        command = f"release {args.release_command}"

    return {
        "command": command,
        "status": "not_implemented",
        "repo": str(Path(args.repo).resolve()),
        "dry_run": bool(getattr(args, "dry_run", False)),
        "message": f"mrp {command} is registered but not implemented yet.",
    }


def emit(result: dict[str, Any], json_output: bool) -> None:
    if json_output:
        print(json.dumps(result, indent=2, sort_keys=True))
        return

    if result["command"] == "inspect" and result["status"] == "ok":
        print(format_inspection(result))
        return
    if result["command"] == "validate":
        print(format_validation(result))
        return
    if result["command"] == "import-site":
        print(format_import(result))
        return
    if result["command"] == "build":
        print(format_build(result))
        return
    if result["command"] == "stage":
        print(format_deployment(result))
        return
    if result["command"] == "verify":
        print(format_verification(result))
        return
    if result["command"] == "approve":
        print(format_approval(result))
        return
    if result["command"] == "status":
        print(format_status(result))
        return
    if result["command"] == "publish":
        print(format_publish(result))
        return
    if result["command"] == "rollback":
        print(format_rollback(result))
        return
    if result["command"] == "release create":
        print(format_release_create(result))
        return

    print(result["message"])


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)

    if args.command == "inspect":
        result = inspect_repository(args.repo)
    elif args.command == "validate":
        result = validate_repository(args.repo, release=args.release)
    elif args.command == "build":
        result = build_repository(args.repo, release=args.release, skip_validate=args.skip_validate)
    elif args.command == "stage":
        result = stage_build(
            args.repo,
            build=args.build,
            target=args.target,
            dry_run=bool(getattr(args, "dry_run", False)),
        )
    elif args.command == "verify":
        result = verify_target(args.repo, target=args.target, release=args.release)
    elif args.command == "approve":
        result = approve(args.repo, release=args.release, build=args.build)
    elif args.command == "status":
        result = status(args.repo, release=args.release)
    elif args.command == "publish":
        result = publish(
            args.repo,
            release=args.release,
            build=args.build,
            auto_approve=bool(getattr(args, "auto_approve", False)),
        )
    elif args.command == "rollback":
        result = rollback(args.repo, to=args.to, yes=bool(getattr(args, "yes", False)))
    elif args.command == "release" and args.release_command == "create":
        result = create_release(args.repo, artist=args.artist, title=args.title, release_type=args.type)
    elif args.command == "import-site":
        result = import_site(args.repo, source=args.source)
    else:
        result = placeholder_result(args)
    emit(result, bool(getattr(args, "json", False)))
    if args.command in {"validate", "build"} and result["status"] == "failed":
        return EXIT_FAILURE
    if args.command == "stage" and result["status"] == "failed":
        if result["stage"] == "safety":
            return EXIT_UNSAFE
        if result["stage"] == "config":
            return EXIT_CONFIG
        return EXIT_DEPLOYMENT
    if args.command == "verify" and result["status"] == "failed":
        return EXIT_FAILURE
    if args.command == "approve" and result["status"] == "failed":
        return EXIT_FAILURE
    if args.command == "status" and result["status"] == "failed":
        return EXIT_CONFIG
    if args.command == "publish" and result["status"] == "failed":
        if result["errors"] and result["errors"][0]["field"] == "safety":
            return EXIT_UNSAFE
        return EXIT_FAILURE
    if args.command == "rollback":
        if result["status"] == "confirmation_required":
            return EXIT_UNSAFE
        if result["status"] == "failed":
            if result["errors"] and result["errors"][0]["field"] == "safety":
                return EXIT_UNSAFE
            return EXIT_FAILURE
    if args.command == "release" and result["status"] == "failed":
        return EXIT_CONFIG
    return EXIT_SUCCESS


if __name__ == "__main__":
    sys.exit(main())
