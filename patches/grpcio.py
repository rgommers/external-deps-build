import re
import sys
from pathlib import Path

unpacked_dir = sys.argv[1]

# This patch is only needed because grpcio doesn't contain a pyproject.toml at all
setup_py = Path(unpacked_dir, "setup.py").read_text()
metadata = Path(unpacked_dir, "_metadata.py").read_text()
match = re.match(r'__version__ = """(\d\.)+"""', metadata)
version = match.group(0) if match else "1.71.0"
setup_py = setup_py.replace("import _metadata", "# import _metadata")
setup_py = setup_py.replace("_metadata.__version__", f"'{version}'")
Path(unpacked_dir, "setup.py").write_text(setup_py)
