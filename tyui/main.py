"""tyui entry point — selects launch mode from argv."""

from __future__ import annotations

import argparse
import os
import sys

from tyui.app import TyuiApp


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="tyui",
        description=(
            "tyui — terminal shell with NC-style file panels, embedded "
            "editor, and agent CLI mode."
        ),
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Optional file or directory. Files open in the editor; "
             "directories open both panels at that path.",
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Start in agent / CLI mode instead of the file manager.",
    )
    return parser.parse_args(argv)


def _resolve_launch_mode(args: argparse.Namespace) -> tuple[str, str | None]:
    """Return (launch_mode, initial_path) given parsed args."""
    if args.cli:
        return ("cli", args.path)  # path optional, used to seed panel cwd
    if args.path is None:
        return ("fm", None)
    if os.path.isfile(args.path):
        return ("editor", args.path)
    # treat anything else (existing dir, missing path) as fm-mode initial cwd
    return ("fm", args.path)


def main() -> None:
    args = _parse_args(sys.argv[1:])
    launch_mode, initial_path = _resolve_launch_mode(args)
    TyuiApp(launch_mode=launch_mode, initial_path=initial_path).run()


def _resolve_we_paths(argv: list[str]) -> list[str]:
    """Return the list of positional file paths for the `we` command."""
    parser = argparse.ArgumentParser(
        prog="we",
        description="we — open one editor window per file, cascaded.",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=[],
        help="Files to edit. Each opens in its own cascaded editor window. "
             "Missing files open empty; directories are skipped.",
    )
    return parser.parse_args(argv).paths


def _resolve_we_launch(paths: list[str]) -> tuple[str, str | None, list[str]]:
    """Pick the launch mode for the `we` command from its positional paths.

    No paths at all -> fall back to the file manager (both panels) instead of
    an empty editor. A lone directory -> seed the file manager at that path.
    Anything with real files -> the usual cascaded-editor `we` mode.
    """
    if not paths:
        return ("fm", None, [])
    file_paths = [p for p in paths if not os.path.isdir(p)]
    if not file_paths:
        # Only directories were given; open the first one in the panels.
        return ("fm", paths[0], [])
    return ("we", None, file_paths)


def main_we() -> None:
    paths = _resolve_we_paths(sys.argv[1:])
    launch_mode, initial_path, file_paths = _resolve_we_launch(paths)
    TyuiApp(
        launch_mode=launch_mode,
        initial_path=initial_path,
        initial_paths=file_paths,
    ).run()


if __name__ == "__main__":
    main()
