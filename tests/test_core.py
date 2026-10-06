import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
from netmed.catalog import build
from netmed.importers.openapi import discover
from netmed.runtime.http import invoke

SPEC = {'openapi': '3.0.3', 'paths': {'/gene/{id}': {'get': {'operationId': 'gene', 'parameters': [{'in': 'path', 'name': 'id', 'required': True, 'schema': {'type': 'string'}}]}}}}

class CoreTests(unittest.TestCase):
    def test_toml_generates_operations_without_function_list(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root/'spec.json').write_text(json.dumps(SPEC))
            (root/'sources.toml').write_text('[sources.example]\nkind="openapi"\nspec="spec.json"\nbase_url="https://example.org"\n')
            result = build(root/'sources.toml', root/'catalog.json')
            self.assertEqual(result['sources']['example']['operations']['gene']['method'], 'GET')

    @patch('netmed.runtime.http.requests.request')
    def test_path_encoded_and_redirects_disabled(self, request):
        response = Mock(ok=True, status_code=200)
        response.json.return_value = {'gene': 'EGFR'}
        request.return_value = response
        source = {'base_url':'https://example.org', 'operations':{'gene':{'method':'GET','path':'/gene/{id}','summary':'','description':'','security':[], 'parameters':SPEC['paths']['/gene/{id}']['get']['parameters']}}}
        self.assertEqual(invoke(source,'gene',['--id','EGFR/other']), {'gene':'EGFR'})
        self.assertEqual(request.call_args.args[1], 'https://example.org/gene/EGFR%2Fother')
        self.assertFalse(request.call_args.kwargs['allow_redirects'])
        response.status_code = 302
        with self.assertRaises(ValueError): invoke(source, 'gene', ['--id','EGFR'])

    def test_secured_operation_is_not_silently_sent_without_credentials(self):
        source = {'operations':{'x':{'summary':'','description':'','parameters':[],'security':[{'key':[]}]}}}
        with self.assertRaises(ValueError): invoke(source,'x',[])

if __name__ == '__main__': unittest.main()
