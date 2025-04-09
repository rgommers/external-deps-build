import shlex
import tarfile
import tomllib
import warnings
from functools import cache
from pathlib import Path
from typing import Annotated

import distro
import typer
from rich import print
from external_metadata_mappings import Ecosystems, Registry, Mapping


HERE = Path(__file__).parent

@cache
def get_known_ecosystems() -> Mapping:
    return Ecosystems.from_url(
        "https://raw.githubusercontent.com/jaimergp/external-metadata-mappings/"
        "refs/heads/main/data/known-ecosystems.json"
    )


@cache
def get_remote_mapping(ecosystem: str) -> Mapping:
    return Mapping.from_url(
        "https://raw.githubusercontent.com/jaimergp/external-metadata-mappings/"
        f"refs/heads/main/data/{ecosystem}.mapping.json"
    )


@cache
def get_remote_registry() -> Registry:
    return Registry.from_url(
        "https://raw.githubusercontent.com/jaimergp/external-metadata-mappings/"
        "refs/heads/main/data/registry.json"
    )


def validate_purl(purl):
    reg = get_remote_registry()
    if purl not in reg.iter_unique_purls():
        raise warnings.warn(f"PURL {purl} is not recognized in the central registry.")
    canonical = {item["id"] for item in reg.iter_canonical()}
    if purl not in canonical:
        for d in reg.iter_by_id(purl):
            if provides := d.get("provides"):
                references = ", ".join(provides)
                break
        else:
            references = None
        msg = f"PURL {purl} is not using a canonical reference."
        if references:
            msg += f" Try with one of: {references}."
        warnings.warn(msg)


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
        if name == 'darwin':
            return 'homebrew'
        elif name in package_manager.keys():
            return name


    warnings.warn(f'No support for distro {distro.id()} yet!')
    # FIXME
    return 'fedora'
    

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
        return list(dict.fromkeys(all_deps))
    else:
        if distro_name is None:
            distro_name = get_distro()
        _mapping = get_remote_mapping(distro_name)
        _mapped_deps = []
        for dep in external_build_deps:
            try:
                _mapped_deps.extend(next(iter(_mapping.iter_by_id(dep)))['specs']['build'])
                _mapped_deps.extend(next(iter(_mapping.iter_by_id(dep)))['specs']['host'])
            except (KeyError, StopIteration):
                raise ValueError(f"Mapping entry for external build dependency `{dep}` missing!")
        
        for dep in external_run_deps:
            try:
                _mapped_deps.extend(next(iter(_mapping.iter_by_id(dep)))['specs']['run'])
            except (KeyError, StopIteration):
                raise ValueError(f"Mapping entry for external run dependency `{dep}` missing!")

        if _uses_c_cpp_compiler(external_build_deps):
            # TODO: handling of non-default Python installs isn't done here,
            # this adds the python-dev/devel package corresponding to the
            # default Python version of the distro.
            _mapped_deps.extend(get_python_dev(distro_name))

        return list(dict.fromkeys(_mapped_deps))


def _uses_c_cpp_compiler(external_build_deps: list[str]) -> bool:
    for compiler in ('dep:virtual/compiler/c', 'dep:virtual/compiler/cpp'):
        if compiler in external_build_deps:
            return True
    return False


def get_python_dev(distro_name) -> list[str]:
    """Return the python development package to list of dependencies

    This is an implicit dependency for packages that use a C or C++ compiler to
    build Python extension modules.
    """
    _mapping = get_remote_mapping(distro_name)
    return next(iter(_mapping.iter_by_id('dep:generic/python')))['specs']['build']


# This should be a registration mechanism - it's here now for demo purposes.
package_manager = {
    'arch': 'pacman',
    'fedora': 'dnf',
    'ubuntu': 'apt-get',
    'conda-forge': 'mamba',
    'darwin': 'brew'
}
package_manager_to_distro = {v: k for k, v in package_manager.items()}

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

    ecosystems = get_known_ecosystems()
    if package_manager:
        for name, details in ecosystems["ecosystems"].items():
            if package_manager in details["package_managers"]:
                distro_name = name
                break
    else:
        distro_name = get_distro()
        package_manager = ecosystems[distro_name]["package_managers"][0]


    if system_install_cmd:
        mapping = get_remote_mapping(distro_name)
        package_manager = mapping.get_package_manager(package_manager)
        external_deps = parse_external(package_name, apply_mapping=True, distro_name=distro_name)
        cmd = mapping.build_install_command(package_manager, external_deps)
        print(shlex.join(cmd))


def entry_point():
    typer.run(main)


if __name__ == '__main__':
    entry_point()
