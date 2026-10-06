import argparse
import json
import os
from urllib.parse import quote
import requests


def value(raw):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def invoke(source, operation_name, arguments, name='netmed'):
    operations = source['operations']
    if operation_name not in operations:
        raise ValueError(f"Unknown operation: {operation_name}")
    operation = operations[operation_name]
    parser = argparse.ArgumentParser(prog=f"{name} {operation_name}", description=operation['summary'] + '\n' + operation['description'])
    supported = {'path', 'query', 'header', 'body'}
    for parameter in operation['parameters']:
        location = parameter['in']
        if location not in supported:
            raise ValueError(f"Unsupported parameter location: {location}")
        schema = parameter.get('schema', parameter)
        parser.add_argument('--' + parameter['name'], dest=parameter['name'], type=value,
                            required=parameter.get('required', False), default=schema.get('default'),
                            help=parameter.get('description', '') + ' Schema: ' + json.dumps(schema))
    if operation.get('requestBody'):
        parser.add_argument('--body', type=value, required=operation['requestBody'].get('required', False),
                            help='JSON request body. Schema: ' + json.dumps(operation['requestBody']))
    parsed = vars(parser.parse_args(arguments))
    if operation['security']:
        raise ValueError('Secured operations are not supported yet; credential binding is pending')
    path = operation['path']
    query, headers, body = {}, {}, None
    for parameter in operation['parameters']:
        name = parameter['name']
        v = parsed[name]
        if v is None:
            continue
        location = parameter['in']
        schema = parameter.get('schema', parameter)
        if location != 'body' and isinstance(v, (list, dict)):
            raise ValueError('Complex parameter serialization is not supported yet; use a JSON body')
        if schema.get('enum') and v not in schema['enum']:
            raise ValueError(f"Invalid value for {name}")
        if location == 'path':
            path = path.replace('{' + name + '}', quote(str(v), safe=''))
        elif location == 'query':
            query[name] = str(v).lower() if isinstance(v, bool) else v
        elif location == 'header':
            if name.lower() in {'host', 'authorization', 'cookie', 'proxy-authorization'}:
                raise ValueError('Sensitive/transport headers cannot be supplied as parameters')
            headers[name] = str(v)
        elif location == 'body':
            body = v
    if operation.get('requestBody'):
        content = operation['requestBody'].get('content', {})
        if 'application/json' not in content:
            raise ValueError('Only application/json request bodies are supported')
        body = parsed['body']
    url = source['base_url'].rstrip('/') + path
    response = requests.request(operation['method'], url, params=query, headers=headers,
                                json=body, timeout=source.get('timeout', 30), allow_redirects=False)
    if 300 <= response.status_code < 400:
        raise ValueError('Redirect refused; request destinations must remain pinned')
    if not response.ok:
        raise ValueError(f"Upstream HTTP {response.status_code}")
    try:
        return response.json()
    except ValueError:
        return response.text
