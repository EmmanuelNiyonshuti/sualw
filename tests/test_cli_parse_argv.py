import pytest

from sualw.cli import parse_argv


def test_no_args_returns_none():
    result = parse_argv(args=[])
    assert result is None


@pytest.mark.parametrize(
    "args",
    [
        ["toggle"],
        ["list"],
        ["stop"],
        ["restart"],
        ["status"],
        ["port"],
        ["logs"],
        ["clean"],
        ["--help"],
        ["-h"],
        ["--version"],
    ],
)
def test_only_subcommand_returns_none(args):
    result = parse_argv(args=args)
    assert result is None


def test_command_with_name_flag():
    result = parse_argv(args=["--name", "myproc", "run", "some", "command"])
    assert result == (["run", "some", "command"], "myproc")


def test_command_with_name_flag_short():
    result = parse_argv(args=["-n", "myproc", "run", "some", "command"])
    assert result == (["run", "some", "command"], "myproc")


def test_command_without_name_flag():
    result = parse_argv(args=["run", "some", "command"])
    assert result == (["run", "some", "command"], None)


def test_name_flag_after_child_command():
    result = parse_argv(args=["run", "some", "command", "--name", "myproc"])
    assert result == (["run", "some", "command", "--name", "myproc"], None)


def test_name_flag_without_value():
    with pytest.raises(ValueError):
        parse_argv(args=["--name"])

    with pytest.raises(ValueError):
        parse_argv(args=["-n"])
