"""Installed distribution metadata without filesystem documentation fallbacks."""

import importlib.metadata


def package_metadata(module_name, package=None):
    names = (
        [package.split("[", 1)[0]]
        if package
        else importlib.metadata.packages_distributions().get(
            module_name.split(".")[0], []
        )
    )
    for name in sorted(set(names)):
        try:
            metadata = importlib.metadata.metadata(name)
        except importlib.metadata.PackageNotFoundError:
            continue
        yield name, metadata


def package_summary(module_name, package=None):
    for name, metadata in package_metadata(module_name, package):
        return {
            "title": metadata.get("Name", name),
            "summary": metadata.get("Summary", ""),
        }
    return {"title": package or module_name.split(".")[0], "summary": ""}


def package_documentation(module_name, package=None):
    """Read distribution descriptions only; never search local README files."""
    documents = []
    for name, metadata in package_metadata(module_name, package):
        text = metadata.get_payload()
        if isinstance(text, str) and text.strip():
            documents.append(
                {
                    "name": metadata.get("Name", name),
                    "version": metadata.get("Version", ""),
                    "content_type": metadata.get(
                        "Description-Content-Type", "text/plain"
                    ),
                    "text": text,
                }
            )
    return documents
