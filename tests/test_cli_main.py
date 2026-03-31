from unittest.mock import patch

import pytest

from sualw.cli import main


class TestMainFunction:
    def test_no_args_calls_app(self):
        with patch("sualw.cli.app") as mock_app:
            with patch("sys.argv", ["sualw"]):
                result = main()
                assert result is None
                mock_app.assert_called_once()

    def test_known_subcommand_calls_app(self):
        known_commands = [
            "toggle",
            "list",
            "stop",
            "restart",
            "status",
            "port",
            "logs",
            "clean",
        ]
        for cmd in known_commands:
            with patch("sualw.cli.app") as mock_app:
                with patch("sys.argv", ["sualw", cmd]):
                    result = main()
                    assert result is None
                    mock_app.assert_called_once()

    def test_help_flag_calls_app(self):
        for flag in ["--help", "-h", "--version"]:
            with patch("sualw.cli.app") as mock_app:
                with patch("sys.argv", ["sualw", flag]):
                    result = main()
                    assert result is None
                    mock_app.assert_called_once()

    def test_custom_command_without_name(self):
        with patch("sys.argv", ["sualw", "python", "script.py"]):
            child_cmd, proc_name = main()
            assert child_cmd == ["python", "script.py"]
            assert proc_name is None

    def test_custom_command_with_long_name_flag(self):
        with patch(
            "sys.argv", ["sualw", "python", "--name", "my_process", "script.py"]
        ):
            child_cmd, proc_name = main()
            assert child_cmd == ["python", "script.py"]
            assert proc_name == "my_process"

    def test_custom_command_with_short_name_flag(self):
        with patch("sys.argv", ["sualw", "npm", "start", "-n", "web_server"]):
            child_cmd, proc_name = main()
            assert child_cmd == ["npm", "start"]
            assert proc_name == "web_server"

    def test_name_flag_at_beginning(self):
        with patch("sys.argv", ["sualw", "--name", "my_app", "node", "index.js"]):
            child_cmd, proc_name = main()
            assert child_cmd == ["node", "index.js"]
            assert proc_name == "my_app"

    def test_name_flag_in_middle(self):
        with patch(
            "sys.argv",
            ["sualw", "node", "--name", "server", "index.js", "--port", "3000"],
        ):
            child_cmd, proc_name = main()
            assert child_cmd == ["node", "index.js", "--port", "3000"]
            assert proc_name == "server"

    def test_complex_command_with_flags_and_options(self):
        """Complex command with multiple flags and options should preserve order."""
        with patch(
            "sys.argv",
            [
                "sualw",
                "docker",
                "run",
                "-d",
                "--name",
                "container",
                "-p",
                "8080:80",
                "nginx",
            ],
        ):
            child_cmd, proc_name = main()
            assert child_cmd == ["docker", "run", "-d", "-p", "8080:80", "nginx"]
            assert proc_name == "container"

    def test_name_flag_with_no_value_exits(self):
        """--name flag with no value should exit with code 1."""
        with patch("sys.argv", ["sualw", "python", "--name"]):
            with patch("sualw.cli.err_console") as mock_console:
                with pytest.raises(SystemExit) as exc_info:
                    main()
                assert exc_info.value.code == 1
                mock_console.print.assert_called_once()
                assert "--name requires a value" in mock_console.print.call_args[0][0]

    def test_short_name_flag_with_no_value_exits(self):
        """Short -n flag with no value should exit with code 1."""
        with patch("sys.argv", ["sualw", "python", "-n"]):
            with patch("sualw.cli.err_console") as mock_console:
                with pytest.raises(SystemExit) as exc_info:
                    main()
                assert exc_info.value.code == 1
                mock_console.print.assert_called_once()

    def test_only_name_flag_no_command_exits(self):
        with patch("sys.argv", ["sualw", "--name", "my_app"]):
            with patch("sualw.cli.err_console") as mock_console:
                with pytest.raises(SystemExit) as exc_info:
                    main()
                assert exc_info.value.code == 1
                mock_console.print.assert_called_once()
                assert "No command provided" in mock_console.print.call_args[0][0]
