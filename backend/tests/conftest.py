import os
import tempfile
from pathlib import Path

# A tiny stand-in for the frontend build, so tests do not need `npm run build`.
_static = Path(tempfile.mkdtemp())
(_static / "index.html").write_text("<!DOCTYPE html><title>Tidy</title><div id='app'></div>", encoding="utf-8")
(_static / "404.html").write_text("<!DOCTYPE html><title>Not found</title>", encoding="utf-8")
os.environ["STATIC_DIR"] = str(_static)
