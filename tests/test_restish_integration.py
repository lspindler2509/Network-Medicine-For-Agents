"""Opt-in tests of the real netmed/Restish request path against a local server."""

import base64
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from netmed.importers.openapi import discover


@unittest.skipUnless(
    os.environ.get("NETMED_RESTISH_TESTS") == "1",
    "Enable real Restish tests with NETMED_RESTISH_TESTS=1",
)
class RestishIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        cls.requests = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.handle_request()

            def do_POST(self):
                self.handle_request()

            def handle_request(self):
                parsed = urlsplit(self.path)
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                record = {
                    "path": parsed.path,
                    "query": parse_qs(parsed.query),
                    "headers": dict(self.headers),
                    "body": base64.b64encode(body).decode(),
                }
                cls.requests.append(record)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                if parsed.path == "/pages":
                    page = int(record["query"].get("page", ["1"])[0])
                    if page == 1:
                        self.send_header(
                            "Link", f'<{cls.base}/pages?page=2>; rel="next"'
                        )
                    value = [{"page": page}]
                elif parsed.path == "/upload":
                    message = BytesParser(policy=policy.default).parsebytes(
                        (
                            "Content-Type: " + self.headers["Content-Type"] + "\r\n\r\n"
                        ).encode()
                        + body
                    )
                    value = {
                        "parts": [
                            {
                                "name": part.get_param(
                                    "name", header="content-disposition"
                                ),
                                "filename": part.get_filename(),
                                "type": part.get_content_type(),
                                "data": base64.b64encode(
                                    part.get_payload(decode=True)
                                ).decode(),
                            }
                            for part in message.iter_parts()
                        ]
                    }
                else:
                    value = record
                self.end_headers()
                self.wfile.write(json.dumps(value).encode())

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.addClassCleanup(server.server_close)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        cls.addClassCleanup(thread.join, 5)
        cls.addClassCleanup(server.shutdown)
        cls.base = f"http://127.0.0.1:{server.server_port}"
        array = {"type": "array", "items": {"type": "string"}}
        response = {
            "200": {
                "description": "Captured request",
                "content": {"application/json": {"schema": {"type": "object"}}},
            }
        }
        paths = {}

        def operation(path, method, name, **kwargs):
            paths[path] = {
                method: {"operationId": name, "responses": response, **kwargs}
            }

        parameters = [
            {
                "name": name,
                "in": "query",
                "style": style,
                "explode": explode,
                "schema": array,
            }
            for name, style, explode in [
                ("repeat", "form", True),
                ("csv", "form", False),
                ("spaces", "spaceDelimited", False),
                ("pipes", "pipeDelimited", False),
            ]
        ]
        parameters += [
            {
                "name": "filter",
                "in": "query",
                "style": "deepObject",
                "explode": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "gene": {"type": "string"},
                        "score": {"type": "integer"},
                    },
                },
            },
            {"name": "X-Genes", "in": "header", "style": "simple", "schema": array},
            {
                "name": "selection",
                "in": "cookie",
                "style": "form",
                "explode": False,
                "schema": array,
            },
        ]
        operation("/query", "get", "queryParams", parameters=parameters)
        for style in ("simple", "label", "matrix"):
            operation(
                "/" + style + "/{ids}",
                "get",
                style + "Path",
                parameters=[
                    {
                        "name": "ids",
                        "in": "path",
                        "required": True,
                        "style": style,
                        "explode": False,
                        "schema": array,
                    }
                ],
            )
        upload = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "literal": {"type": "string"},
                "file": {"type": "string", "format": "binary"},
                "files": {
                    "type": "array",
                    "items": {"type": "string", "format": "binary"},
                },
                "meta": {"type": "object", "properties": {"gene": {"type": "string"}}},
            },
        }
        operation(
            "/upload",
            "post",
            "uploadFiles",
            requestBody={
                "content": {
                    "multipart/form-data": {
                        "schema": upload,
                        "encoding": {
                            "file": {"contentType": "application/octet-stream"},
                            "files": {"contentType": "text/plain"},
                            "meta": {"contentType": "application/json"},
                        },
                    }
                }
            },
        )
        operation(
            "/form",
            "post",
            "sendForm",
            requestBody={
                "content": {
                    "application/x-www-form-urlencoded": {
                        "schema": {
                            "type": "object",
                            "properties": {"gene": {"type": "string"}, "genes": array},
                        }
                    }
                }
            },
        )
        operation(
            "/raw",
            "post",
            "sendRaw",
            requestBody={
                "content": {
                    "application/octet-stream": {
                        "schema": {"type": "string", "format": "binary"}
                    }
                }
            },
        )
        common = cls.root / "common.json"
        common.write_text(
            json.dumps(
                {
                    "GeneQuery": {
                        "type": "object",
                        "required": ["gene", "count"],
                        "additionalProperties": False,
                        "properties": {
                            "gene": {"type": "string", "enum": ["EGFR", "ERBB2"]},
                            "count": {"type": "integer", "minimum": 1},
                        },
                    }
                }
            )
        )
        operation(
            "/validated",
            "post",
            "validateBody",
            requestBody={
                "content": {
                    "application/json": {
                        "schema": {"allOf": [{"$ref": "./common.json#/GeneQuery"}]}
                    }
                }
            },
        )
        operation(
            "/pages",
            "get",
            "listPages",
            parameters=[{"name": "page", "in": "query", "schema": {"type": "integer"}}],
        )
        document = {
            "openapi": "3.1.0",
            "info": {"title": "Local request capture", "version": "1"},
            "servers": [{"url": cls.base}],
            "paths": paths,
        }
        spec = cls.root / "openapi.json"
        spec.write_text(json.dumps(document))
        from netmed.building.restish import download

        executable = os.environ.get("NETMED_RESTISH") or download(cls.root / "native")
        cls.env = {
            **os.environ,
            "NETMED_DATA_DIR": str(cls.root / "data"),
            "NETMED_RESTISH": executable,
        }
        # Loopback HTTP is restricted to this fixture; production registry URLs stay HTTPS.
        with patch.dict(os.environ, cls.env):
            source = {"kind": "openapi", "base_url": cls.base, "spec": str(spec)}
            source.update(discover(source, "capture"))
        cls.catalog = cls.root / "catalog.json"
        cls.catalog.write_text(json.dumps({"sources": {"capture": source}}))

    def run_cli(self, *arguments, success=True, cwd=None):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "netmed",
                "--catalog",
                str(self.catalog),
                "capture",
                *arguments,
            ],
            env=self.env,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
        return result

    def test_query_arrays_deep_object_header_and_cookie(self):
        result = self.run_cli(
            "query-params",
            "--repeat",
            "EGFR",
            "--repeat",
            "ERBB2",
            "--csv",
            "EGFR,ERBB2",
            "--spaces",
            "EGFR,ERBB2",
            "--pipes",
            "EGFR,ERBB2",
            "--filter-gene",
            "EGFR",
            "--filter-score",
            "7",
            "--x-genes",
            "EGFR,ERBB2",
            "--selection",
            "EGFR,ERBB2",
        )
        record = json.loads(result.stdout)
        self.assertEqual(
            record["query"],
            {
                "repeat": ["EGFR", "ERBB2"],
                "csv": ["EGFR,ERBB2"],
                "spaces": ["EGFR ERBB2"],
                "pipes": ["EGFR|ERBB2"],
                "filter[gene]": ["EGFR"],
                "filter[score]": ["7"],
            },
        )
        headers = {key.lower(): value for key, value in record["headers"].items()}
        self.assertEqual(headers["x-genes"], "EGFR,ERBB2")
        self.assertIn("selection=EGFR%2CERBB2", headers["cookie"])

    def test_path_array_styles(self):
        for style, expected in [
            ("simple", "EGFR,ERBB2"),
            ("label", ".EGFR,ERBB2"),
            ("matrix", ";ids=EGFR,ERBB2"),
        ]:
            with self.subTest(style=style):
                record = json.loads(self.run_cli(style + "-path", "EGFR,ERBB2").stdout)
                self.assertEqual(record["path"], "/" + style + "/" + expected)

    def test_multipart_file_bytes_names_arrays_and_part_types(self):
        file = self.root / "genes.txt"
        content = b"EGFR\nERBB2\n\x00\xff"
        file.write_bytes(content)
        reference = file.as_posix()
        result = self.run_cli(
            "upload-files",
            f"name: test, literal: @@EGFR, file: @{reference}, files: [@{reference},@{reference}], meta.gene: EGFR",
        )
        parts = json.loads(result.stdout)["parts"]
        files = [part for part in parts if part["filename"]]
        self.assertEqual([part["name"] for part in files], ["file", "files", "files"])
        for part in files:
            self.assertEqual(part["filename"], "genes.txt")
            self.assertEqual(base64.b64decode(part["data"]), content)
        self.assertEqual(files[0]["type"], "application/octet-stream")
        self.assertEqual(files[1]["type"], "text/plain")
        meta = next(part for part in parts if part["name"] == "meta")
        self.assertEqual(meta["type"], "application/json")
        self.assertEqual(json.loads(base64.b64decode(meta["data"])), {"gene": "EGFR"})
        literal = next(part for part in parts if part["name"] == "literal")
        self.assertEqual(base64.b64decode(literal["data"]), b"@EGFR")

    def test_missing_upload_is_rejected_before_http(self):
        count = len(self.requests)
        self.run_cli(
            "upload-files",
            f"file: @{(self.root / 'missing.txt').as_posix()}",
            success=False,
        )
        self.assertEqual(len(self.requests), count)

    def test_urlencoded_form(self):
        record = json.loads(
            self.run_cli("send-form", "gene: EGFR, genes: [EGFR,ERBB2]").stdout
        )
        body = base64.b64decode(record["body"]).decode()
        # Restish 2.3.0 uses bracket-style array keys for form bodies. This is
        # native behavior, not full coverage of OpenAPI per-field encoding.
        self.assertEqual(
            parse_qs(body), {"gene": ["EGFR"], "genes[]": ["EGFR", "ERBB2"]}
        )

    def test_raw_binary_body(self):
        file = self.root / "payload.bin"
        content = bytes(range(256))
        file.write_bytes(content)
        # A whole-body Windows drive path contains a colon, which Restish's
        # shorthand parser can interpret as a mapping. Use its portable relative
        # @file syntax, with an explicit working directory.
        record = json.loads(
            self.run_cli("send-raw", "@" + file.name, cwd=self.root).stdout
        )
        self.assertEqual(base64.b64decode(record["body"]), content)

    def test_external_ref_help_generation_and_default_validation_with_opt_out(self):
        help_text = self.run_cli("validate-body", "--help").stdout
        self.assertIn("gene", help_text)
        count = len(self.requests)
        invalid = 'gene: UNKNOWN, count: "bad"'
        self.run_cli("validate-body", invalid, success=False)
        self.assertEqual(len(self.requests), count)
        self.run_cli("validate-body", "gene: EGFR, count: 2")
        self.assertEqual(len(self.requests), count + 1)
        self.run_cli("validate-body", invalid, "--rsh-validate=false")
        self.assertEqual(len(self.requests), count + 2)
        self.run_cli("validate-body", "--rsh-generate-body")
        self.assertEqual(len(self.requests), count + 2)

    def test_next_link_pagination_and_explicit_limits(self):
        records = json.loads(self.run_cli("list-pages").stdout)
        self.assertEqual(records, [{"page": 1}, {"page": 2}])
        records = json.loads(self.run_cli("list-pages", "--rsh-no-paginate").stdout)
        self.assertEqual(records, [{"page": 1}])
        limited = self.run_cli("list-pages", "--rsh-max-pages", "1")
        self.assertEqual(json.loads(limited.stdout), [{"page": 1}])
        self.assertIn("limit", limited.stderr.lower())
        records = json.loads(self.run_cli("list-pages", "--rsh-max-pages", "0").stdout)
        self.assertEqual(records, [{"page": 1}, {"page": 2}])

    def test_api_update_stages_native_backend_and_preserves_old_execution(self):
        import io
        from netmed.catalog import load
        from netmed.runtime import source_updates
        from netmed.runtime.restish import invoke

        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.dict(os.environ, self.env),
        ):
            root = Path(temporary).resolve()
            document = {
                "openapi": "3.0.3",
                "info": {"title": "Refresh fixture", "version": "1"},
                "servers": [{"url": self.base}],
                "paths": {
                    "/old": {
                        "get": {
                            "operationId": "oldOperation",
                            "responses": {"200": {"description": "Capture"}},
                        }
                    }
                },
            }
            spec = root / "old.json"
            spec.write_text(json.dumps(document))
            source = {
                "kind": "openapi",
                "spec": str(spec),
                "spec_origin": "https://example.org/openapi.json",
                "base_url": self.base,
            }
            source.update(discover(source, "refresh"))
            old_config = Path(source["restish"]["config"])
            old_bytes = old_config.read_bytes()
            catalog = root / "catalog.json"
            catalog.write_text(json.dumps({"sources": {"refresh": source}}))
            before_catalog = catalog.read_bytes()
            before_backends = set(
                (Path(self.env["NETMED_DATA_DIR"]) / "restish").iterdir()
            )
            document["paths"]["/fresh"] = {
                "get": {
                    "operationId": "newOperation",
                    "responses": {"200": {"description": "Capture"}},
                }
            }
            with patch("netmed.importers.openapi.requests.get") as request:
                request.return_value.status_code = 200
                request.return_value.text = json.dumps(document)
                preview = source_updates.update(
                    catalog, dry_run=True, use_updates=False, progress=io.StringIO()
                )
                self.assertEqual(preview["sources"][0]["status"], "would_update")
                self.assertEqual(before_catalog, catalog.read_bytes())
                self.assertEqual(
                    before_backends,
                    set((Path(self.env["NETMED_DATA_DIR"]) / "restish").iterdir()),
                )
                result = source_updates.update(
                    catalog, use_updates=False, progress=io.StringIO()
                )
            self.assertEqual(result["sources"][0]["status"], "updated")
            updated = load(catalog)["sources"]["refresh"]
            with (
                tempfile.TemporaryFile(mode="w+") as output,
                tempfile.TemporaryFile(mode="w+") as errors,
            ):
                self.assertEqual(
                    invoke(updated, ["new-operation"], stdout=output, stderr=errors), 0
                )
                output.seek(0)
                self.assertEqual(json.load(output)["path"], "/fresh")
            old_help = io.StringIO()
            self.assertEqual(
                invoke(source, ["--help"], stdout=old_help, stderr=io.StringIO()), 0
            )
            self.assertNotIn("new-operation", old_help.getvalue())
            self.assertEqual(old_bytes, old_config.read_bytes())
