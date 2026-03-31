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


def _process_cmd() -> None:
    pass


def main() -> None | tuple[list[str], str | None]:
    """
    Reads sys.argv before Typer sees it to decide which path to take:
      - Known subcommand -> hand full `argv` to Typer.
      - Unknown first token -> it's a command to background. Parse only
        --name/-n ourselves, pass everything else to _start_shelveited() verbatim.
    """
    args = sys.argv[1:]

    if not args:
        app()
        return None

    # Find the first argument token that isn't a flag (doesn't start with -).
    # tells us whether the user is running a subcommand
    # or wants to background something.
    first_non_flag: str | None = None
    for arg in args:
        if not arg.startswith("-"):
            first_non_flag = arg
            break

    if first_non_flag is None or first_non_flag in _SUBCOMMANDS:
        # It's a known subcommand, or just flags like --help.
        # Let Typer parse and dispatch it normally.
        app()
        return None
    # Parse --name/-n out of the args manually. We can't use Typer for this
    # because Typer would also try to parse the child command's flags.
    #
    # Everything remaining after we remove --name and its value is the
    # command to pass to subprocess — untouched, in the original order.

    proc_name: str | None = None
    child_cmd = list(args)

    for flag in ("--name", "-n"):
        if flag in child_cmd:
            flag_index = child_cmd.index(flag)
            if flag_index + 1 >= len(child_cmd):
                # User typed `shelveit --name` with nothing after it.
                err_console.print(f"[red]X[/red]  {flag} requires a value.")
                sys.exit(1)
            proc_name = child_cmd[flag_index + 1]
            # Remove both the flag and its value from the command list.
            del child_cmd[flag_index : flag_index + 2]
            break

    if not child_cmd:
        err_console.print("[red]X[/red]  No command provided.")
        sys.exit(1)

    return child_cmd, proc_name
