import argparse
from pathlib import Path
import re
import tarfile
import urllib.request
import warnings

from pypi_json import PyPIJSON


def download_sdist(package_name, sdist_dir):
    with PyPIJSON() as client:
        metadata = client.get_metadata(package_name)

    url = None
    for item in metadata.get_wheel_tag_mapping():
        if isinstance(item, list):  # sdist
            assert len(item) == 1 and str(item[0]).endswith('tar.gz')
            url = str(item[0])

    if url is None:
        raise RuntimeError(f"No sdist for package {package_name} found.")

    fname_sdist = url.split('/')[-1]
    urllib.request.urlretrieve(url, sdist_dir / fname_sdist)
    return fname_sdist


_toml_setuptools = """[build-system]
requires = ["setuptools", "versioninfo"]
build-backend = "setuptools.build_meta"
"""


def untar_sdist(fname_sdist, sdist_dir):
    tar = tarfile.open(sdist_dir / fname_sdist)

    for info in tar.getmembers():
        name = info.name
        if '/' in name and name.split('/')[1] == 'pyproject.toml':
            break

    tar.extractall(path=sdist_dir)

    pyproject_toml = sdist_dir / info.name.split('/')[0] / 'pyproject.toml'
    if not (pyproject_toml).exists():
        warnings.warn(f"{fname_sdist} does not contain a pyproject.toml file", UserWarning)
        with open(pyproject_toml, 'w') as f:
            f.write(_toml_setuptools)

    return pyproject_toml


def append_external_metadata(fname_sdist, package_name):
    pyproject_toml = Path(fname_sdist)
    pyproject_toml_contents = pyproject_toml.read_text()
    external_metadata = Path("external_metadata", f"{package_name}.toml").read_text()
    if external_metadata not in pyproject_toml_contents:
        pyproject_toml.write_text(pyproject_toml_contents + "\n" + external_metadata)


def apply_patches(package_name, unpacked_dir):
    if package_name == "grpcio":
        setup_py = Path(unpacked_dir, "setup.py").read_text()
        metadata = Path(unpacked_dir, "_metadata.py").read_text()
        match = re.match(r'__version__ = """(\d\.)+"""', metadata)
        version = match.group(0) if match else "1.71.0"
        setup_py = setup_py.replace("import _metadata", "# import _metadata")
        setup_py = setup_py.replace("_metadata.__version__", f"'{version}'")
        Path(unpacked_dir, "setup.py").write_text(setup_py)


def create_new_sdist(sdist_name, sdist_dir, amended_dir):
    dirname = sdist_name.split('.tar.gz')[0]
    with tarfile.open(amended_dir / sdist_name.lower().replace("_", "-"), "w:gz") as tar:
        tar.add(sdist_dir / dirname, arcname=dirname)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('package_name')
    args = parser.parse_args()

    package_name = args.package_name

    amended_dir = Path('./sdist/_amended')
    amended_dir.mkdir(exist_ok=True, parents=True)
    sdist_dir = amended_dir.parent

    fname_sdist = download_sdist(package_name, sdist_dir)
    fname_pyproject_toml = untar_sdist(fname_sdist, sdist_dir)
    append_external_metadata(fname_pyproject_toml, package_name)
    apply_patches(package_name, fname_pyproject_toml.parent)
    create_new_sdist(fname_sdist, sdist_dir, amended_dir)
