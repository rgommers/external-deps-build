import shlex
import tarfile
import tomllib
import warnings
from functools import cache
from pathlib import Path
from typing import Annotated

import distro
import requests
import typer
from rich import print

HERE = Path(__file__).parent

# This should be a registration mechanism - it's here now for demo purposes.
package_manager = {
    'arch': 'pacman',
    'fedora': 'dnf',
    'ubuntu': 'apt-get',
    'conda-forge': 'mamba',
    'darwin': 'brew'
}


@cache
def get_remote_mapping(ecosystem: str) -> dict:
    r = requests.get(
        "https://raw.githubusercontent.com/jaimergp/external-metadata-mappings/"
        f"refs/heads/main/data/{ecosystem}.mapping.json"
    )
    r.raise_for_status()
    return r.json()


@cache
def get_remote_registry() -> dict:
    r = requests.get(
        "https://raw.githubusercontent.com/jaimergp/external-metadata-mappings/"
        "refs/heads/main/data/registry.json"
    )
    r.raise_for_status()
    return r.json()


@cache
def get_purls_by_type() -> dict:
    definitions = get_remote_registry()["definitions"]
    canonical, non_canonical = [], []
    for d in definitions:
        if provides := d.get("provides"):
            if isinstance(provides, str):
                provides = [provides]
            if any(item.startswith("pkg:") for item in provides):
                non_canonical.append(d["id"])
            else:
                canonical.append(d["id"])
        else:
            canonical.append(d["id"])
    
    return {
        "canonical": set(canonical),
        "non-canonical": set(non_canonical),
        "all": set(canonical + non_canonical),
    }


def validate_purl(purl):
    purls = get_purls_by_type()
    if purl not in purls["all"]:
        raise warnings.warn(f"PURL {purl} is not recognized in the central registry.")
    if purl not in purls["canonical"]:
        for d in get_remote_registry()["definitions"]:
            if purl == d["id"] and d.get("provides"):
                references = ", ".join(d["provides"])
                break
        else:
            references = None
        msg = f"PURL {purl} is not using a canonical reference."
        if references:
            msg += f" Try with one of: {references}."
        warnings.warn(msg)
    

def get_specs(mapping, purl: str) -> dict[str, list[str]]:
    "Return the first result in the mapping, for now"
    specs = None
    for m in mapping.get("mappings", ()):
        if m["id"] == purl:
            if specs := m.get("specs"):
                specs = specs
                break
            elif specs_from := m.get("specs_from"):
                return get_specs(mapping, specs_from)
            else:
                raise ValueError("'specs' or 'specs_from' are required")
    if not specs:
        raise ValueError(f"Didn't find purl '{purl}' in mapping '{mapping}'")
    elif isinstance(specs, str):
        specs = {"build": [specs], "host": [specs], "run": [specs]}
    elif hasattr(specs, "items"): # assert all fields are present
        specs.setdefault("build", [])
        specs.setdefault("host", [])
        specs.setdefault("run", [])
    else: # list
        specs = {"build": specs, "host": specs, "run": specs}
    return specs


def read_pyproject(package_name: str):
    fname_sdist = sorted((HERE / "../../sdist/_amended/").glob(f"{package_name}-*.tar.gz"))[-1]
    with tarfile.open(fname_sdist) as tar:
        fileobj_toml = None
        for info in tar.getmembers():
            name = info.name
            if '/' in name and name.split('/')[1] == 'pyproject.toml':
                fileobj_toml = tar.extractfile(info)
                break

        if fileobj_toml is None:
            raise ValueError("Could not read pyproject.toml file from sdist")
        
        tomldata = tomllib.load(fileobj_toml)
    return tomldata


def get_distro():
    for name in [distro.id(), distro.like()]:
        if name in package_manager.keys():
            return name

    warnings.warn(f'No support for distro {distro.id()} yet!')
    # FIXME
    return 'fedora'


def get_package_manager():
    name = get_distro()
    return package_manager[name]
    

def print_toml_key(key, table):
    if key in table:
        print(f'[cyan]{key}[/]:')
        if isinstance(table[key], list):
            for item in table[key]:
                print(f'[bright_black]  {item}[/]')
        elif isinstance(table[key], dict):
            for key2 in table[key]:
                print(f'  [bright_black]{key2}[/]:')
                for item in table[key][key2]:
                    print(f'[bright_black]    {item}[/]')


def parse_external(package_name: str, show: bool = False, apply_mapping: bool = False,
                   distro_name: str = None) -> list[str]:
    """Adds optional build/host deps in 'extra' by default, because those are typically desired"""
    external_build_deps = []
    external_run_deps = []
    toml = read_pyproject(package_name)
    if 'external' in toml:
        external = toml['external']
        for key in ('build-requires', 'host-requires', 'dependencies'):
            if key in external:
                if 'requires' in key:
                    external_build_deps.extend(external[key])
                else:
                    external_run_deps.extend(external[key])
                if show:
                    print_toml_key(key, external)

        for key in ('optional-build-requires', 'optional-host-requires', 'optional-dependencies'):
            if key in external:
                if 'requires' in key:
                    external_build_deps.extend(external[key]['extra'])
                if show:
                    print_toml_key(key, external)

    if not apply_mapping:
        all_deps = external_build_deps.copy()
        all_deps.extend(external_run_deps)
        return all_deps
    else:
        if distro_name is None:
            distro_name = get_distro()
        _mapping = get_remote_mapping(distro_name)
        _mapped_deps = []
        for dep in external_build_deps:
            try:
                _mapped_deps.extend(get_specs(_mapping, dep)['build'])
                _mapped_deps.extend(get_specs(_mapping, dep)['host'])
            except KeyError:
                raise ValueError(f"Mapping entry for external build dependency `{dep}` missing!")
        
        for dep in external_run_deps:
            try:
                _mapped_deps.extend(get_specs(_mapping, dep)['run'])
            except KeyError:
                raise ValueError(f"Mapping entry for external run dependency `{dep}` missing!")

        if _uses_c_cpp_compiler(external_build_deps):
            # TODO: handling of non-default Python installs isn't done here,
            # this adds the python-dev/devel package corresponding to the
            # default Python version of the distro.
            _mapped_deps.extend(get_python_dev(distro_name))

        return _mapped_deps


def _uses_c_cpp_compiler(external_build_deps: list[str]) -> bool:
    for compiler in ('virtual:compiler/c', 'virtual:compiler/cpp'):
        if compiler in external_build_deps:
            return True
    return False


def get_python_dev(distro_name) -> list[str]:
    """Return the python development package to list of dependencies

    This is an implicit dependency for packages that use a C or C++ compiler to
    build Python extension modules.
    """
    _mapping = get_remote_mapping(distro_name)
    return get_specs(_mapping, 'pkg:generic/python')['build']


def main(package_name: str,
    external: Annotated[bool, typer.Option(help="Show external dependencies for package")] = False,
    validate: Annotated[bool, typer.Option(help="Validate external dependencies against central registry")] = False,
    system_install_cmd: Annotated[bool, typer.Option(
        help="Show install command with system package manager for `--pypi` and/or "
             "`--external` dependencies")] = False,
    package_manager: Annotated[str, typer.Option(help="If given, use this package manager rather than auto-detect one")] = "",
    ) -> None:
    """
    py-show: inspecting package dependencies
    """
    if external:
        purls = parse_external(package_name, show=not system_install_cmd)
        if purls and validate:
            for purl in purls:
                validate_purl(purl)

    distro_name = None
    if package_manager:
        if package_manager in ('conda', 'mamba', 'micromamba'):
            distro_name = 'conda-forge'
        elif package_manager == 'brew':
            distro_name = 'homebrew'
    else:
        package_manager = get_package_manager()
        distro_name = get_distro()
        if distro_name == 'darwin':
            distro_name = 'homebrew'

    if system_install_cmd:
        mapping = get_remote_mapping(distro_name)
        install_command = []
        for mgr in mapping["package_managers"]:
            if mgr["name"] == package_manager:
                install_command = mgr["install_command"]
                break
        else:
            raise ValueError(f"Ecosystem {distro_name} has no package manager named {package_manager}")
        external_deps = parse_external(package_name, apply_mapping=True, distro_name=distro_name)
        # Deduplicate in-place
        external_deps = list(dict.fromkeys(external_deps))
        print(shlex.join(install_command + external_deps))


def entry_point():
    typer.run(main)


if __name__ == '__main__':
    entry_point()
