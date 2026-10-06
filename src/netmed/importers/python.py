"""Delegate module/class/method discovery and documentation to Python Fire."""
import importlib


def invoke(source, arguments, name='netmed'):
    import fire
    fire.Fire(importlib.import_module(source["module"]), command=arguments, name=name)
