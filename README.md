# Build packages from PyPI with [external] metadata

This is a proof of concept of using `[external]` metadata - i.e., metadata for
Python packages of build and runtime dependencies on non-Python packages, see
[PEP 725](https://peps.python.org/pep-0725/) - plus a "name mapping mechanism"
to build wheels from source in clean Docker containers with a plain:

```
pip install <package-name> --no-binary <package-name>
```

The purpose of the name mapping mechanism is to translate `[external]` metadata,
which uses [PURL (Package URLs)](https://github.com/package-url/purl-spec)-like
identifiers (`dep:`) plus "virtual dependencies" for more abstract requirements like "a
C++ compiler", into system package manager specific package names.

The CLI interface to the name mapping mechanism (available in 
[`external-metadata-mappings`][2]) is provided by the [`pyproject-external`][1]
library (`python -m pyproject_external`). It can also show install commands specific
to the system package manager, which is potentially useful for end users.

*Note: all of this is currently experimental, and under the hood doesn't look
anything like a production-ready version would. Please don't use this for
anything beyond experimenting.*


## Experimental method

The [scripts](scripts/), CI setup and results in the repo basically do the following:

1. Determine which of the top 150 most downloaded packages (current monthly
   downloads, data from
   [hugovk/top-pypi-packages](https://github.com/hugovk/top-pypi-packages))
   have platform-specific wheels on PyPI. Saved in [`top_packages/`](top_packages/).
2. For each such package, determine its external dependencies and write those
   into a `package_name.toml` file. See [`external_metadata/`](external_metadata/).
3. In a matrix'ed set of CI jobs, build each package separately from source in
   a clean Docker container, with the external dependencies being installed
   with a "system" package manager. This is currently done for three package
   managers and distros: `dnf` (Fedora), `pacman` (Arch Linux), and
   `micromamba` (conda-forge). The CI jobs do roughly the following:

   - Spin up a clean Docker container for the base OS
   - Install `python` with the system package manager
   - Download the sdist for the latest release of the package being built from PyPI
   - Patch the sdist to append the `[external]` metadata at the end of
     `pyproject.toml` (for packages without a `pyproject.toml`, inject a basic
     3-line one to enable `setuptools.build_meta` as the build backend)
   - Use the `pyproject-external` tool to read the `[external]` metadata and generate an
     install command for the system package manager from that.
   - Invoke the package manager to install the external dependencies.
   - Build the package with `pip install <amended-sdist>.tar.gz` (no custom
     config-settings, environment variables or other tweaks allowed).
   - If the build succeeds, do a basic `import pkg_import_name` check.

4. Analyze the [results](results/) - successful package builds yes/no, duration,
   dependencies used.


## Results

*These are the main results as of <!-- DATE -->05 Sep 2025<!-- /DATE -->.*

Overall number of successful builds per distro:

<!-- DISTRO_TABLE -->
| distro      | success   |
|:------------|:----------|
| Arch        | 36/37     |
| Fedora      | 34/37     |
| conda-forge | 36/37     |
<!-- /DISTRO_TABLE -->


Average CI job duration per package for the heaviest builds:

<!-- DURATION_TABLE -->
| package       | duration   |
|:--------------|:-----------|
| grpcio        | 16m 59s    |
| scipy         | 13m 4s     |
| pyarrow       | 7m 16s     |
| grpcio-tools  | 6m 10s     |
| pandas        | 5m 5s      |
| numpy         | 4m 24s     |
| scikit-learn  | 3m 47s     |
| pynacl        | 3m 10s     |
| pydantic-core | 2m 39s     |
| lxml          | 2m 8s      |
| matplotlib    | 2m 4s      |
| cryptography  | 1m 49s     |
<!-- /DURATION_TABLE -->


Per-package success/failure:

<!-- SUCCESS_TABLE -->
| package            | Arch               | conda-forge        | Fedora             |
|:-------------------|:-------------------|:-------------------|:-------------------|
| charset-normalizer | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: |
| cryptography       | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: |
| pyyaml             | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: |
| numpy              | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: |
| protobuf           | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: |
| pandas             | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: |
| markupsafe         | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: |
| cffi               | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: |
| psutil             | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: |
| lxml               | :x:                | :heavy_check_mark: | :x:                |
| sqlalchemy         | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: |
| aiohttp            | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: |
| grpcio             | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: |
| pyarrow            | :heavy_check_mark: | :heavy_check_mark: | :x:                |
| wrapt              | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: |
| frozenlist         | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: |
| coverage           | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: |
| pillow             | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: |
| greenlet           | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: |
| yarl               | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: |
| multidict          | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: |
| scipy              | :heavy_check_mark: | :x:                | :x:                |
| httptools          | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: |
| pynacl             | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: |
| psycopg2-binary    | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: |
| rpds-py            | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: |
| bcrypt             | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: |
| scikit-learn       | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: |
| msgpack            | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: |
| matplotlib         | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: |
| regex              | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: |
| kiwisolver         | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: |
| pydantic-core      | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: |
| pyrsistent         | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: |
| grpcio-tools       | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: |
| pycryptodomex      | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: |
| google-crc32c      | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: |
<!-- /SUCCESS_TABLE -->


[1]: https://github.com/jaimergp/pyproject-external
[2]: https://github.com/jaimergp/external-metadata-mappings
