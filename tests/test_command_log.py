import contextlib
from datetime import datetime
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from netmed.cli import main
from netmed.runtime.command_log import record_command, read_commands
from data_isolation import setUpModule, tearDownModule  # noqa: F401


class CommandLogTests(unittest.TestCase):
    def test_cli_clear_removes_history_and_its_own_record(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"NETMED_DATA_DIR": directory}),
        ):
            record_command(["jobs"])
            with (
                patch.object(sys, "argv", ["netmed", "logs", "--clear"]),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(main(), 0)
            self.assertFalse((Path(directory) / "logs.txt").exists())

    def test_read_history_tail_and_cli_output(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"NETMED_DATA_DIR": directory}),
        ):
            self.assertEqual(read_commands(), "")
            record_command(["help"])
            record_command(["jobs"])
            self.assertTrue(read_commands(1).endswith("netmed jobs\n"))
            with (
                patch.object(sys, "argv", ["netmed", "logs", "--tail", "1"]),
                contextlib.redirect_stdout(io.StringIO()) as output,
            ):
                self.assertEqual(main(), 0)
            self.assertEqual(len(output.getvalue().splitlines()), 1)
            self.assertTrue(output.getvalue().endswith("netmed logs --tail 1\n"))

    def test_append_keeps_one_line_per_command_with_timezone_without_environment(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(
                os.environ,
                {"NETMED_DATA_DIR": directory, "UNRELATED_KEY": "not-for-logging"},
            ),
        ):
            arguments = [
                "drugstone",
                "map_nodes",
                '--nodes=["EGFR", "A B"]',
                "line\nbreak",
            ]
            path = record_command(arguments)
            record_command(["--help"])
            text = path.read_text()
            records = text.splitlines()
            self.assertEqual(len(records), 2)
            timestamp, command = records[0][1:].split("] ", 1)
            self.assertTrue(command.startswith("netmed drugstone map_nodes "))
            self.assertIn("A B", command)
            self.assertIn(r"line\nbreak", command)
            self.assertIsNotNone(datetime.fromisoformat(timestamp).utcoffset())
            self.assertTrue(records[1].endswith("] netmed --help"))
            self.assertNotIn("not-for-logging", text)

    def test_help_is_logged_before_argument_parser_exits(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"NETMED_DATA_DIR": directory}),
            patch.object(sys, "argv", ["netmed", "--help"]),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            with self.assertRaises(SystemExit) as stopped:
                main()
            self.assertEqual(stopped.exception.code, 0)
            record = (Path(directory) / "logs.txt").read_text()
            self.assertTrue(record.endswith("] netmed --help\n"))

    def test_logging_failure_does_not_block_command(self):
        with (
            patch(
                "netmed.runtime.command_log.record_command", side_effect=PermissionError
            ),
            patch.object(sys, "argv", ["netmed", "help"]),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()) as errors,
        ):
            self.assertEqual(main(), 0)
        self.assertIn("execution continues", errors.getvalue())
