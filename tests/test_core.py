import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from netmed.catalog import build
from netmed.importers.openapi import load_document, documentation
from netmed.errors import UserError

SPEC = {
    "openapi": "3.0.3",
    "info": {"title": "Example API", "version": "1"},
    "paths": {},
}


class CoreTests(unittest.TestCase):
    def test_source_cannot_shadow_management_command(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "sources.toml"
            config.write_text('[sources.logs]\nkind="python"\nmodule="json"\n')
            with patch("netmed.importers.python.discover") as discover:
                with self.assertRaisesRegex(ValueError, "conflicts with CLI command"):
                    build(config, root / "catalog.json")
                discover.assert_not_called()

    def test_docs_preserve_metadata_without_fetching_links(self):
        with tempfile.TemporaryDirectory() as directory:
            document = {
                **SPEC,
                "info": {**SPEC["info"], "description": "Overview"},
                "externalDocs": {"url": "https://example.org/docs"},
                "tags": [{"name": "genes"}],
            }
            spec = Path(directory) / "spec.json"
            spec.write_text(json.dumps(document))
            with patch("netmed.importers.openapi.requests.get") as request:
                result = documentation(str(spec))
                request.assert_not_called()
            self.assertEqual(
                result, {k: document[k] for k in ("info", "externalDocs", "tags")}
            )

    def test_swagger_is_rejected_before_backend_provisioning(self):
        with tempfile.TemporaryDirectory() as directory:
            spec = Path(directory) / "spec.json"
            spec.write_text(json.dumps({"swagger": "2.0"}))
            with (
                self.assertRaisesRegex(UserError, "Swagger/OpenAPI 2"),
                patch("netmed.runtime.restish.prepare") as prepare,
            ):
                load_document(str(spec))
            prepare.assert_not_called()

    def test_toml_delegates_operations_to_restish(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "spec.json").write_text(json.dumps(SPEC))
            (root / "sources.toml").write_text(
                '[sources.example]\nkind="openapi"\nspec="spec.json"\nbase_url="https://example.org"\n'
            )
            backend = {
                "version": "2.3.0",
                "config": "/example/config",
                "cache": "/example/cache",
                "source": "example",
            }
            with patch(
                "netmed.runtime.restish.prepare",
                return_value={"restish": backend, "operation_count": 3},
            ) as prepare:
                result = build(root / "sources.toml", root / "catalog.json")["sources"][
                    "example"
                ]
            self.assertEqual(result["restish"], backend)
            self.assertEqual(result["operation_count"], 3)
            self.assertNotIn("operations", result)
            self.assertNotIn("documentation", result)
            self.assertEqual(prepare.call_args.args[1], "example")
            self.assertEqual(result["spec"], str((root / "spec.json").resolve()))
