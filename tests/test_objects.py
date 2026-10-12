import json
import os
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from netmed.runtime import object_store as objects

from netmed.worker import objects as worker
from netmed.worker.callbacks import parse_callback


class ObjectTests(unittest.TestCase):
    def test_metadata_preview_keeps_complete_arguments_on_disk(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"NETMED_DATA_DIR": directory}),
        ):
            request = {
                "objects_root": str(objects.directory_for()),
                "module": "example",
                "environment_id": "test",
                "original_arguments": ["query", "x" * 53000],
                "object_options": {"--save-object": "large"},
            }
            _, save = worker.object_io(request)
            identity = json.loads(save([1]))["saved_objects"][0]["id"]
            brief = objects.display_metadata(identity)
            self.assertNotIn("arguments", brief)
            self.assertEqual(len(brief["arguments_preview"]), 500)
            self.assertTrue(brief["arguments_truncated"])
            self.assertEqual(
                objects.display_metadata(identity, full=True)["arguments"],
                request["original_arguments"],
            )

    def test_show_launches_original_environment_and_forwards_fire_arguments(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"NETMED_DATA_DIR": directory}),
        ):
            environment_id = "a" * 24
            request = {
                "objects_root": str(objects.directory_for()),
                "module": "example",
                "environment_id": environment_id,
                "original_arguments": [],
                "object_options": {"--save-object": "saved"},
            }
            _, save = worker.object_io(request)
            identity = json.loads(save([1]))["saved_objects"][0]["id"]
            with self.assertRaisesRegex(ValueError, "unavailable"):
                objects.show(identity, [])
            root = Path(directory) / "environments" / environment_id
            executable = root / (
                "Scripts/python.exe" if os.name == "nt" else "bin/python"
            )
            executable.parent.mkdir(parents=True)
            executable.touch()
            (root / "environment.json").write_text(json.dumps({"id": environment_id}))
            with patch("subprocess.run") as run:
                run.return_value.returncode = 0
                self.assertEqual(
                    objects.show("saved", ["-", "to_csv", "--index=False"]), 0
                )
                self.assertEqual(run.call_args.args[0][0], str(executable.resolve()))
                sent = json.loads(run.call_args.kwargs["input"])
                self.assertEqual(sent["action"], "show_object")
                self.assertEqual(sent["object_id"], identity)
                self.assertEqual(sent["arguments"], ["to_csv", "--index=False"])
            (root / "environment.json").write_text(json.dumps({"id": "wrong"}))
            with self.assertRaisesRegex(ValueError, "does not match"):
                objects.show(identity, [])

    def test_labels_selectors_identity_and_ambiguity(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"NETMED_DATA_DIR": directory}),
        ):
            request = {
                "objects_root": str(objects.directory_for()),
                "module": "example",
                "environment_id": "test",
                "original_arguments": [],
                "object_options": {"--save-object": "lung_graph"},
            }
            load, save = worker.object_io(request)
            identity = json.loads(save({"nodes": [1, 2]}))["saved_objects"][0]["id"]
            self.assertIs(load("@object:lung_graph"), load("@object:" + identity))
            self.assertEqual(load('@object:lung_graph["nodes"][0]'), 1)
            self.assertEqual(objects.inspect_object("lung_graph")["id"], identity)
            _, options = objects.execution_options(["--save-updated-object=lung_graph"])
            self.assertEqual(options["--save-updated-object"], identity)
            json.loads(save([3]))
            with self.assertRaisesRegex(worker.ObjectError, "Ambiguous"):
                load("@object:lung_graph")
            with self.assertRaisesRegex(ValueError, "Ambiguous"):
                objects.inspect_object("lung_graph")
            self.assertEqual(load("@object:" + identity)["nodes"], [1, 2])

    def test_cleanup_rejects_metadata_path_escape(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"NETMED_DATA_DIR": directory}),
        ):
            root = Path(directory)
            victim = root / "victim"
            victim.mkdir()
            (victim / "keep").write_text("keep")
            identity = "a" * 32
            artifact = root / "objects" / identity
            artifact.mkdir(parents=True)
            (artifact / "metadata.json").write_text(json.dumps({"id": "../victim"}))
            (artifact / "object.pkl").write_bytes(b"not loaded")
            with self.assertRaisesRegex(ValueError, "metadata ID"):
                objects.clean([identity])
            self.assertTrue((victim / "keep").exists())

    def test_bundle_selectors_structure_and_invalid_expressions(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"NETMED_DATA_DIR": directory}),
        ):
            request = {
                "objects_root": str(objects.directory_for()),
                "module": "example",
                "environment_id": "test",
                "original_arguments": [],
                "object_options": {"--save-object": "bundle"},
            }
            load, save = worker.object_io(request)
            identity = json.loads(save(({"graph": [1, 2]}, {"net": 3})))[
                "saved_objects"
            ][0]["id"]
            ref = "@object:" + identity
            whole = load(ref)
            self.assertIs(load(ref + "[0]"), whole[0])
            self.assertIs(load(ref + '[0]["graph"]'), whole[0]["graph"])
            self.assertEqual(load(ref + '[-1]["net"]'), 3)
            self.assertEqual(
                objects.inspect_object(identity)["structure"]["items"][0]["selector"],
                "[0]",
            )
            for suffix in (
                "[20]",
                '["bad"]',
                '[0]["missing"]',
                ".items",
                "[1+1]",
                "[0:1]",
                "[True]",
                '[__import__("os")]',
            ):
                with self.assertRaises(worker.ObjectError, msg=suffix):
                    load(ref + suffix)
            request["object_options"] = {"--save-updated-object": identity}
            whole[0]["graph"].append(4)
            updated = json.loads(save(None))["saved_objects"][0]["id"]
            fresh, _ = worker.object_io(request)
            self.assertEqual(fresh("@object:" + updated + '[0]["graph"]'), [1, 2, 4])
            self.assertEqual(fresh(ref + '[0]["graph"]'), [1, 2])

    def test_explicit_lambda_compilation_and_errors(self):
        callback = parse_callback("@lambda:lambda node: node != 1")
        self.assertTrue(callback(2))
        self.assertFalse(callback(1))
        self.assertEqual(parse_callback("@lambda:lambda x: len(x)")([1, 2]), 2)
        for expression in ("@lambda:42", "@lambda:lambda x:"):
            with self.assertRaisesRegex(worker.ObjectError, "Invalid @lambda"):
                parse_callback(expression)
        with self.assertRaises(AttributeError):
            parse_callback("@lambda:lambda x: x.missing")(1)

    def test_roundtrip_identity_nested_refs_metadata_and_cleanup(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"NETMED_DATA_DIR": directory}),
        ):
            request = {
                "objects_root": str(objects.directory_for()),
                "module": "example",
                "environment_id": "env",
                "original_arguments": ["example"],
                "object_options": {"--save-object": "data"},
            }
            load, save = worker.object_io(request)
            value = {"rows": [1, 2]}
            info = json.loads(save(value))["saved_objects"][0]
            identity = info["id"]
            resolved = load(["@object:" + identity, {"nested": "@object:" + identity}])
            self.assertEqual(resolved[0], value)
            self.assertIs(resolved[0], resolved[1]["nested"])
            self.assertEqual(objects.list_objects()[0]["label"], "data")
            self.assertEqual(objects.inspect_object(identity)["environment_id"], "env")
            self.assertEqual(
                len(objects.clean([identity, "data"], True)["would_remove"]), 1
            )
            self.assertTrue(Path(objects.inspect_object(identity)["path"]).exists())
            self.assertEqual(len(objects.clean([identity, "data"])["removed"]), 1)
            self.assertEqual(objects.list_objects(), [])

    def test_failed_save_not_published_and_invalid_cleanup_is_atomic(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"NETMED_DATA_DIR": directory}),
        ):
            request = {
                "objects_root": str(objects.directory_for()),
                "module": "example",
                "environment_id": "env",
                "original_arguments": [],
                "object_options": {"--save-object": "bad"},
            }
            load, save = worker.object_io(request)
            with self.assertRaisesRegex(worker.ObjectError, "Cannot save"):
                save(iter(x for x in [1, 2]))
            self.assertEqual(list(objects.directory_for().iterdir()), [])
            identity = json.loads(save([1]))["saved_objects"][0]["id"]
            with self.assertRaises(ValueError):
                objects.clean([identity, "../escape"])
            self.assertTrue(Path(objects.inspect_object(identity)["path"]).exists())
            with self.assertRaisesRegex(worker.ObjectError, "Invalid object"):
                load("@object:../escape")

    def test_mutation_saves_new_artifact_preserving_original(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"NETMED_DATA_DIR": directory}),
        ):
            request = {
                "objects_root": str(objects.directory_for()),
                "module": "example",
                "environment_id": "env",
                "original_arguments": [],
                "object_options": {"--save-object": "initial"},
            }
            _, save = worker.object_io(request)
            original = json.loads(save([1]))["saved_objects"][0]["id"]
            request["object_options"] = {"--save-updated-object": original}
            load, save = worker.object_io(request)
            load("@object:" + original).append(2)
            new = json.loads(save(None))["saved_objects"][0]["id"]
            fresh, _ = worker.object_io(request)
            self.assertEqual(fresh("@object:" + original), [1])
            self.assertEqual(fresh("@object:" + new), [1, 2])
            self.assertEqual(objects.inspect_object(new)["parent_object"], original)

    def test_failed_load_reports_missing_dependency(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"NETMED_DATA_DIR": directory}),
        ):
            request = {
                "objects_root": str(objects.directory_for()),
                "module": "example",
                "environment_id": "env",
                "original_arguments": [],
                "object_options": {"--save-object": "initial"},
            }
            _, save = worker.object_io(request)
            identity = json.loads(save([1]))["saved_objects"][0]["id"]
            load, _ = worker.object_io(request)
            with patch(
                "pickle.load", side_effect=ModuleNotFoundError("missing dependency")
            ):
                with self.assertRaisesRegex(
                    worker.ObjectError, "required packages and versions"
                ):
                    load("@object:" + identity)

    def test_saved_output_keeps_child_diagnostics_off_json_stdout(self):
        path = str(Path(__file__).parents[1] / "src/netmed/worker/objects.py")
        code = """import importlib.util,sys,subprocess
from netmed.worker import objects as w
with w.saved_output() as output:
 print('parent progress')
 subprocess.run([sys.executable,'-c',"print('child progress')"],check=True)
 output.write('{"saved_objects": []}\\n');output.flush()
"""
        result = subprocess.run(
            [sys.executable, "-c", code, path],
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"saved_objects": []})
        self.assertIn("parent progress", result.stderr)
        self.assertIn("child progress", result.stderr)

    def test_options_preserve_native_arguments(self):
        args, options = objects.execution_options(
            ["Graph", "--save-object=graph", "--data=[1]"]
        )
        self.assertEqual(args, ["Graph", "--data=[1]"])
        self.assertEqual(options, {"--save-object": "graph"})
        with self.assertRaises(ValueError):
            objects.execution_options(["--save-object"])
