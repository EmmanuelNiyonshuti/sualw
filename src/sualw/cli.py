import sys

import typer
from rich.console import Console

app = typer.Typer(
    name="sualw",
    help="A small cli tool to silence process logs and get them back on demand.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

err_console = Console(stderr=True)

_SUBCOMMANDS = frozenset(
    {
        "toggle",
        "list",
        "stop",
        "restart",
        "status",
        "port",
        "logs",
        "clean",
        "--help",
        "-h",
        "--version",
    }
)


def process_cmd() -> None:
    pass


def parse_argv(args: list[str]) -> None | tuple[list[str], str | None]:
    """
    Parses the command and process name from the given args.
    Returns a tuple of (child_cmd, proc_name) if a command is found, or None if no command is provided.
    """
    if not args:
        return None

    proc_name: str | None = None
    i = 0

    while i < len(args):
        arg = args[i]
        if arg in ("--name", "-n"):
            if i + 1 >= len(args):
                raise ValueError(f"Flag '{arg}' provided without a value.")
            proc_name = args[i + 1]
            i += 2
        elif arg.startswith("-"):
            i += 1
        else:
            break

    child_cmd = args[i:]

    if not child_cmd or child_cmd[0] in _SUBCOMMANDS:
        return None

    if not child_cmd:
        raise ValueError("No command provided to run.")

    return child_cmd, proc_name


def main() -> None | tuple[list[str], str | None]:
    """
    Reads sys.argv before Typer sees it to decide which path to take:
      - Known subcommand -> hand full `argv` to Typer.
      - Unknown first token -> it's a command to background. Parse only
        --name/-n ourselves, pass everything else to _start_shelveited() verbatim.
    """
    args = sys.argv[1:]
    try:
        result = parse_argv(args)
    except ValueError as e:
        err_console.print(f"[red]X[/red]  {e}")
        sys.exit(1)
    if result is None:
        app()
        return None

    child_cmd, proc_name = result
    process_cmd(child_cmd, proc_name)
