import sys
from pathlib import Path

import typer
from rich.console import Console

from . import registry
from .proc import CommandNotFoundError, Process, StartupError

app = typer.Typer(
    name="sualw",
    help="A small cli tool to silence process logs and get them back on demand.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

err_console = Console(stderr=True)
console = Console()

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


def exit_with_error(message: str) -> None:
    err_console.print(f"[red]X[/red]  {message}")
    sys.exit(1)


def process_cmd(child_cmd: list[str], proc_name: str | None = None) -> None:
    """
    child_cmd is the raw list of tokens from sys.argv e.g.
    ["flask", "run", "--debug"] exactly as the user typed them.
    We pass it straight through to Process.start().

    proc_name overrides the default name (binary name) if the user passed
    --name. e.g. `sualw --name api uvicorn main:app` registers as "api".
    """
    proc_name = proc_name or Path(child_cmd[0]).name

    existing = Process.load(proc_name)
    if existing is not None:
        if existing.alive:
            exit_with_error(
                f"[bold]{proc_name}[/bold] is already running "
                f"[dim](pid {existing.pid})[/dim]\n\n"
                f"  stop it:  [bold]sualw stop {proc_name}[/bold]\n"
                f"  rename:   [bold]sualw --name <alias> {' '.join(child_cmd)}[/bold]"
            )
        else:
            registry.delete_entry(proc_name)

    try:
        proc = Process.start(child_cmd, proc_name)
    except CommandNotFoundError as exc:
        exit_with_error(f"Command not found: [bold]{exc}[/bold]")
        return
    except StartupError as exc:
        err_console.print(
            f"\n[red]✗[/red]  [bold]{proc_name}[/bold] exited immediately "
            f"[dim](code {exc.exit_code})[/dim]\n"
        )
        if exc.log_tail:
            err_console.print("[dim]output[/dim]")
            for line in exc.log_tail.splitlines():
                err_console.print(f"  {line}")
            err_console.print(f"[dim]full log -> sualw logs {proc_name}[/dim]\n")
        sys.exit(1)

    console.print(
        f"\n[green]Ok.[/green]  [bold]{proc_name}[/bold] is running quietly  "
        f"[dim](pid {proc.pid})[/dim]\n"
        f"   [dim]log     ->  {proc.log}[/dim]\n"
        f"   [dim]watch   ->  sualw toggle {proc_name}[/dim]\n"
        f"   [dim]stop    ->  sualw stop {proc_name}[/dim]\n"
    )


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
        --name/-n ourselves, pass everything else to _start_sualwed() verbatim.
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
