import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from netmed.cli import main
from data_isolation import setUpModule, tearDownModule  # noqa: F401


class HelpTests(unittest.TestCase):
    def setUp(self):
        log = patch("netmed.runtime.command_log.record_command")
        log.start()
        self.addCleanup(log.stop)

    def test_catalog_override_does_not_change_job_data_directory(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"NETMED_DATA_DIR": directory}),
            patch.object(
                sys, "argv", ["netmed", "--catalog", "/different/catalog.json", "jobs"]
            ),
            contextlib.redirect_stdout(io.StringIO()),
            patch("netmed.runtime.jobs.list_jobs", return_value=[]) as listing,
        ):
            self.assertEqual(main(), 0)
            listing.assert_called_once_with(Path(directory).resolve() / "jobs")

    def test_api_docs_fetch_spec_on_demand_without_following_external_links(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog = Path(directory) / "catalog.json"
            docs = {
                "info": {"title": "Example API", "description": "Gene queries"},
                "externalDocs": {"url": "https://example.org/docs"},
                "tags": [],
            }
            catalog.write_text(
                json.dumps(
                    {
                        "sources": {
                            "example": {
                                "kind": "openapi",
                                "spec": "https://example.org/openapi.json",
                            }
                        }
                    }
                )
            )
            with (
                patch.object(
                    sys,
                    "argv",
                    ["netmed", "--catalog", str(catalog), "docs", "example"],
                ),
                contextlib.redirect_stdout(io.StringIO()) as out,
                patch("requests.get") as request,
            ):
                request.return_value.status_code = 200
                request.return_value.text = json.dumps({"openapi": "3.0.3", **docs})
                self.assertEqual(main(), 0)
                request.assert_called_once_with(
                    "https://example.org/openapi.json",
                    timeout=30,
                    allow_redirects=False,
                )
            self.assertIn("Gene queries", out.getvalue())
            self.assertIn("https://example.org/docs", out.getvalue())

    def test_docs_read_installed_metadata_on_demand(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog = Path(directory) / "catalog.json"
            catalog.write_text(
                json.dumps(
                    {"sources": {"example": {"kind": "python", "module": "example"}}}
                )
            )
            with (
                patch.object(
                    sys,
                    "argv",
                    ["netmed", "--catalog", str(catalog), "docs", "example"],
                ),
                contextlib.redirect_stdout(io.StringIO()) as out,
                patch(
                    "netmed.documentation.documentation",
                    return_value=[
                        {
                            "name": "example-dist",
                            "version": "1.0",
                            "text": "# Algorithm docs",
                        }
                    ],
                ) as read,
            ):
                self.assertEqual(main(), 0)
                read.assert_called_once_with({"kind": "python", "module": "example"})
            self.assertIn("# Algorithm docs", out.getvalue())
            self.assertIn("example-dist 1.0", out.getvalue())

    def test_help_uses_selected_catalog_without_preparing_environments(self):
        with tempfile.TemporaryDirectory() as d:
            catalog = Path(d) / "catalog.json"
            catalog.write_text(
                json.dumps(
                    {
                        "sources": {
                            "example": {
                                "kind": "python",
                                "source_metadata": {
                                    "title": "Example API",
                                    "summary": "Example source",
                                },
                                "discovery_metadata": {"operations": {"map": {}}},
                            }
                        }
                    }
                )
            )
            with (
                patch.object(
                    sys, "argv", ["netmed", "--catalog", str(catalog), "--help"]
                ),
                contextlib.redirect_stdout(io.StringIO()) as out,
                patch(
                    "netmed.runtime.environments.UvEnvironmentManager.ensure"
                ) as install,
            ):
                with self.assertRaises(SystemExit) as exit:
                    main()
                self.assertEqual(exit.exception.code, 0)
                install.assert_not_called()
            text = out.getvalue()
            self.assertIn("example", text)
            self.assertIn("Example source", text)
            self.assertNotIn("discovered operations", text)
            self.assertNotIn("lazy discovery", text)
            self.assertIn("jobs [job-id]", text)

    def test_description_override_and_automatic_fallback(self):
        for override, expected in [
            ("Custom purpose", "Custom purpose"),
            ("", "Automatic summary"),
        ]:
            with (
                self.subTest(override=override),
                tempfile.TemporaryDirectory() as directory,
            ):
                catalog = Path(directory) / "catalog.json"
                catalog.write_text(
                    json.dumps(
                        {
                            "sources": {
                                "demo": {
                                    "kind": "python",
                                    "description": override,
                                    "source_metadata": {
                                        "title": "Demo",
                                        "summary": "Automatic summary",
                                    },
                                }
                            }
                        }
                    )
                )
                with (
                    patch.object(
                        sys, "argv", ["netmed", "--catalog", str(catalog), "help"]
                    ),
                    contextlib.redirect_stdout(io.StringIO()) as out,
                ):
                    self.assertEqual(main(), 0)
                self.assertIn(expected, out.getvalue())
                if override:
                    self.assertNotIn("Automatic summary", out.getvalue())

    def test_missing_catalog_still_shows_bootstrap_help(self):
        with (
            patch.object(
                sys,
                "argv",
                ["netmed", "--catalog", "/nonexistent/catalog.json", "help"],
            ),
            contextlib.redirect_stdout(io.StringIO()) as out,
        ):
            self.assertEqual(main(), 0)
        self.assertIn("netmed build sources.toml", out.getvalue())

    def test_management_commands_validate_arguments_before_execution(self):
        for arguments in (
            ["prepare"],
            ["_job-worker"],
            ["jobs", "kill"],
            ["jobs", "active", "extra"],
            ["sources", "extra"],
            ["build", "one.toml", "extra.toml"],
        ):
            with (
                self.subTest(arguments=arguments),
                patch.object(sys, "argv", ["netmed", *arguments]),
                contextlib.redirect_stderr(io.StringIO()) as errors,
            ):
                with self.assertRaises(SystemExit) as exit:
                    main()
                self.assertEqual(exit.exception.code, 2)
                self.assertIn("error:", errors.getvalue())
                self.assertNotIn("Traceback", errors.getvalue())

    def test_locally_written_errors_are_shown(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog = Path(directory) / "catalog.json"
            catalog.write_text('{"sources":{}}')
            with (
                patch.object(
                    sys,
                    "argv",
                    ["netmed", "--catalog", str(catalog), "prepare", "missing"],
                ),
                contextlib.redirect_stderr(io.StringIO()) as errors,
            ):
                self.assertEqual(main(), 1)
            self.assertIn("Unknown source: missing", errors.getvalue())

    def test_overview_hides_disabled_and_replaces_generic_api_title(self):
        from netmed.cli import NetmedParser

        with tempfile.TemporaryDirectory() as directory:
            catalog = Path(directory) / "catalog.json"
            catalog.write_text(
                json.dumps(
                    {
                        "sources": {
                            "proteins": {
                                "kind": "openapi",
                                "source_metadata": {"title": "OpenAPI definition"},
                                "description": "Protein searches",
                            }
                        },
                        "disabled_sources": {
                            "not_ready": {"disabled_reason": "Not supported"}
                        },
                    }
                )
            )
            parser = NetmedParser()
            parser.catalog_path = str(catalog)
            text = parser.format_help()
            self.assertNotIn("OpenAPI definition", text)
            self.assertNotIn("not_ready", text)
            self.assertNotIn("Disabled sources (", text)
            self.assertIn("Protein searches", text)
            self.assertIn("including disabled sources", text)

    def test_sources_retains_disabled_entries(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"NETMED_DATA_DIR": directory}),
        ):
            catalog = Path(directory) / "catalog.json"
            catalog.write_text(
                json.dumps(
                    {
                        "sources": {},
                        "disabled_sources": {
                            "pending": {"disabled_reason": "Unsupported"}
                        },
                    }
                )
            )
            with (
                patch.object(
                    sys, "argv", ["netmed", "--catalog", str(catalog), "sources"]
                ),
                contextlib.redirect_stdout(io.StringIO()) as output,
            ):
                self.assertEqual(main(), 0)
            self.assertIn("pending", json.loads(output.getvalue())["disabled_sources"])
