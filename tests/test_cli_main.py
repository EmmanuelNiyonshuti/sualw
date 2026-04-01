import sys
from unittest.mock import Mock

import pytest

from sualw.cli import main


def test_main_slice_argv_calls_parse_argv(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sys, "argv", ["sualw", "run", "some", "command"])
    parse_argv_mock = Mock(return_value=(["run", "some", "command"], None))
    monkeypatch.setattr("sualw.cli.parse_argv", parse_argv_mock)
    monkeypatch.setattr("sualw.cli.process_cmd", Mock())

    main()

    parse_argv_mock.assert_called_once_with(["run", "some", "command"])
