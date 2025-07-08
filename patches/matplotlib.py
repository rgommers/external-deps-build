import sys
from pathlib import Path

unpacked_dir = sys.argv[1]

# avoids missing symbol errors due to lto=on with some compilers
# https://github.com/matplotlib/matplotlib/issues/28357
meson_build = Path(unpacked_dir, "meson.build").read_text()
meson_build = meson_build.replace("'b_lto=true'", "'b_lto=false'")
Path(unpacked_dir, "meson.build").write_text(meson_build)
