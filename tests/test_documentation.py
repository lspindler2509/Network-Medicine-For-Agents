import json
import unittest
from unittest.mock import Mock, patch
from netmed.documentation import python_documentation as documentation


class DocumentationTests(unittest.TestCase):
    def test_external_docs_use_pypi_version_without_provisioning(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            "info": {
                "name": "Example-Package",
                "version": "1.2",
                "description": "# Docs",
            }
        }
        sources = [
            ({"package": "example_package", "version": "==1.2"}, "1.2"),
            (
                {
                    "package": "example_package",
                    "version": ">=1",
                    "discovery_metadata": {"packages": {"Example-Package": "1.3"}},
                },
                "1.3",
            ),
        ]
        for source, version in sources:
            with (
                self.subTest(source=source),
                patch(
                    "netmed.documentation.requests.get", return_value=response
                ) as request,
                patch("netmed.documentation.UvEnvironmentManager.ensure") as ensure,
            ):
                self.assertEqual(documentation(source)[0]["text"], "# Docs")
                request.assert_called_once_with(
                    f"https://pypi.org/pypi/example_package/{version}/json",
                    timeout=30,
                    allow_redirects=False,
                )
                ensure.assert_not_called()
        with patch("netmed.documentation.requests.get") as request:
            with self.assertRaisesRegex(ValueError, "resolved package version"):
                documentation({"package": "example", "version": ">=1"})
            request.assert_not_called()

    def test_local_docs_use_worker_metadata_without_pypi(self):
        environment = {
            "python": "python",
            "directory": "local-env",
            "worker": "worker.py",
        }
        response = Mock(
            returncode=0,
            stdout='[{"name":"local", "version":"1", "text":"Local docs"}]',
        )
        with (
            patch(
                "netmed.documentation.UvEnvironmentManager.ensure",
                return_value=environment,
            ),
            patch("netmed.documentation.subprocess.run", return_value=response) as run,
            patch("netmed.documentation.requests.get") as request,
        ):
            self.assertEqual(
                documentation({"path": "/local/package", "module": "local"})[0]["text"],
                "Local docs",
            )
            self.assertEqual(
                json.loads(run.call_args.kwargs["input"])["action"], "docs"
            )
            request.assert_not_called()
