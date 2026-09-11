"""Read KEY=value lines out of .env into os.environ, without a dependency.

The project's own convention is environment variables; this only means the
values can live in the gitignored .env file instead of every shell. Anything
already set in the environment wins.
"""

import os

DEFAULT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


def load(path=DEFAULT_PATH):
    """Load path into os.environ if it exists; return the keys that were set."""
    if not os.path.exists(path):
        return []
    added = []
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
                added.append(key)
    return added
