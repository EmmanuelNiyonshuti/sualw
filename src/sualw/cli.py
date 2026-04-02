import sys
from pathlib import Path
from typing import Annotated

import typer
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import registry
from .proc import CommandNotFoundError, Process, StartupError
from .tail import tail_log

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


class Icon:
    OK = "\u2713"
    FAIL = "\u2717"
    WARN = "\u26a0"
    RELOAD = "\u27f3"


def exit_with_error(message: str) -> None:
    err_console.print(f"[red]{Icon.FAIL}[/red]  {message}")
    sys.exit(1)


def _load_proc_or_exit(name: str) -> Process:
    proc = Process.load(name)
    if proc is None:
        exit_with_error(
            f"No process named [bold]{name}[/bold]. "
            f"Run [bold]sualw list[/bold] to see active processes run by sualw."
        )
    return proc  # type: ignore[return-value]


@app.command()
def toggle(
    name: Annotated[str, typer.Argument(help="Name of the process to toggle.")],
    history: Annotated[
        bool,
        typer.Option("--history", "-H", help="Replay full log before streaming live."),
    ] = False,
) -> None:

    proc = _load_proc_or_exit(name)

    if not proc.alive:
        console.print(
            f"\n[yellow]{Icon.WARN}[/yellow]  [bold]{name}[/bold] is not running\n"
        )
        try:
            tail_log(proc.log_path, from_start=True)
        except KeyboardInterrupt:
            pass
        return

    mode_label = "history + live" if history else "live"
    console.print(
        f"\n[cyan]{Icon.RELOAD}[/cyan]  [bold]{name}[/bold]  [dim]({mode_label})[/dim] - Ctrl+C to detach\n"
    )
    try:
        tail_log(proc.log_path, from_start=history)
    except KeyboardInterrupt:
        pass
    console.print("\n[dim]Detached.[/dim]")


@app.command("list")
def list_cmd() -> None:
    all_procs = Process.load_all()

    if not all_procs:
        console.print("[dim]Nothing sualwd yet.  Try:  sualw <command> [args...][/dim]")
        return

    t = Table(box=box.SIMPLE, header_style="bold", show_edge=False, padding=(0, 1))
    t.add_column("NAME", style="bold", no_wrap=True)
    t.add_column("PID", style="dim", no_wrap=True)
    t.add_column("STATUS", no_wrap=True)
    t.add_column("UPTIME", style="dim", no_wrap=True)
    t.add_column("COMMAND", style="dim", overflow="fold", max_width=44)

    for proc_name, proc in all_procs.items():
        if proc.alive:
            status_str = "[green]running[/green]"
            uptime_str = proc.uptime
        elif proc.exit_code is not None:
            color = "red" if proc.exit_code != 0 else "yellow"
            status_str = f"[{color}]exited({proc.exit_code})[/{color}]"
            uptime_str = "-"
        else:
            status_str = "[red]stopped[/red]"
            uptime_str = "-"

        t.add_row(
            proc_name, str(proc.pid), status_str, uptime_str, " ".join(proc.command)
        )

    console.print()
    console.print(t)


@app.command()
def status(
    name: Annotated[str, typer.Argument(help="Process name.")],
) -> None:
    proc = _load_proc_or_exit(name)

    if proc.alive:
        state_str = "[green]running[/green]"
        uptime_str = proc.uptime
        port_list = proc.ports
    elif proc.exit_code is not None:
        color = "red" if proc.exit_code != 0 else "yellow"
        state_str = f"[{color}]exited ({proc.exit_code})[/{color}]"
        uptime_str = "-"
        port_list = []
    else:
        state_str = "[red]stopped[/red]"
        uptime_str = "-"
        port_list = []

    port_str = (
        "  ".join(f":{p}" for p in port_list)
        if port_list
        else "[dim]none detected[/dim]"
    )

    info_table = Table(box=None, show_header=False, padding=(0, 1), show_edge=False)
    info_table.add_column(style="dim", no_wrap=True, min_width=9)
    info_table.add_column(no_wrap=False)
    info_table.add_row("status", state_str)
    info_table.add_row("pid", f"[dim]{proc.pid}[/dim]  pgid {proc.pgid}")
    info_table.add_row("uptime", uptime_str)
    info_table.add_row("ports", port_str)
    info_table.add_row("started", proc.started_at.replace("T", "  "))
    info_table.add_row("log", f"[dim]{proc.log}[/dim]")
    info_table.add_row("command", " ".join(proc.command))

    console.print()
    console.print(
        Panel(info_table, title=f"[bold]{name}[/bold]", expand=False, padding=(0, 1))
    )
    console.print()

    if proc.log_path.exists():
        recent_lines = proc.log_path.read_text(errors="replace").splitlines()
        console.print(
            "[dim]recent output[/dim]  [dim](sualw toggle to follow live)[/dim]\n"
        )
        for line in recent_lines[-16:] if len(recent_lines) > 16 else recent_lines:
            console.print(f"  [dim]{line}[/dim]")
    else:
        console.print("[dim]no log yet[/dim]")
    console.print()


@app.command()
def stop(
    name: Annotated[str, typer.Argument(help="name of the process to stop.")],
    force: Annotated[
        bool, typer.Option("--force", "-f", help="Send SIGKILL instead of SIGTERM.")
    ] = False,
) -> None:

    proc = _load_proc_or_exit(name)
    signal_sent = proc.stop(force=force)
    sig_name = "SIGKILL" if force else "SIGTERM"

    if signal_sent:
        console.print(
            f"\n[green]{Icon.OK}[/green]  [bold]{name}[/bold] received {sig_name}.\n"
        )
    else:
        console.print(
            f"\n[yellow]{Icon.WARN}[/yellow]  [bold]{name}[/bold] was already dead — removed from registry.\n"
        )


def process_cmd(child_cmd: list[str], proc_name: str | None = None) -> None:
    """
    child_cmd is the raw list of tokens from sys.argv e.g.
    ["flask", "run", "--debug"] exactly as the user typed them.
    We pass it through Process.start().

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
            f"\n[red]{Icon.FAIL}[/red]  [bold]{proc_name}[/bold] exited immediately "
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
        err_console.print(f"[red]{Icon.FAIL}[/red]  {e}")
        sys.exit(1)
    if result is None:
        app()
        return None

    child_cmd, proc_name = result
    process_cmd(child_cmd, proc_name)
