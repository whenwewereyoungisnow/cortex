"""Slice 0 smoke test: the CLI parser knows all six subcommands."""

import pytest

from cortex.cli import build_parser

COMMANDS = ["ingest", "refresh", "search", "stats", "check", "doctor"]


@pytest.mark.parametrize("command", COMMANDS)
def test_subcommand_parses(command):
    argv = [command, "q"] if command == "search" else [command]
    args = build_parser().parse_args(argv)
    assert args.command == command
