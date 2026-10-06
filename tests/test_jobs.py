import json
import tempfile
import time
import unittest
from pathlib import Path
from netmed.catalog import build
from netmed.runtime.jobs import launch

class JobTests(unittest.TestCase):
    def test_detached_job_completes_and_stores_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root/'sources.toml'
            config.write_text('[sources.demo]\nkind="python"\nmodule="json"\n')
            catalog = root/'catalog.json'
            build(config, catalog)
            job = launch(catalog, ['demo', 'dumps', '{"gene":"EGFR"}'], root/'jobs')
            status_path = Path(job['directory'])/'status.json'
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                state = json.loads(status_path.read_text())
                if state['state'] in ('completed','failed'):
                    break
                time.sleep(.05)
            self.assertEqual(state['state'], 'completed', (Path(job['directory'])/'stderr.txt').read_text())
            self.assertIn('EGFR', (Path(job['directory'])/'result.txt').read_text())
