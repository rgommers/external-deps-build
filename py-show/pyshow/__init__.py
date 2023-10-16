import tarfile
import tomllib
from typing import Annotated
import warnings

import distro
from rich import print
import typer


# This should be a registration mechanism - it's here now for demo purposes.
package_manager = {
    'arch': 'pacman',
    'fedora': 'dnf',
    'ubuntu': 'apt-get',
}

package_mgr_install_commands = {
    'apt-get': 'sudo apt-get install --yes',
    'dnf': 'sudo dnf install -y',
    'pacman': 'sudo pacman -Syu',
}

# For external dependencies; for Python/PyPI ones we will make use of existing
# metadata files that distros already have.
package_mapping = {}
package_mapping['fedora'] = {
    'virtual:compiler/c': 'gcc',
    'virtual:compiler/cpp': 'gcc-c++',
    'virtual:compiler/fortran': 'gcc-gfortran',
    'virtual:compiler/rust': 'rust',
}

package_mapping['arch'] = {
    'virtual:compiler/c': 'gcc',
    'virtual:compiler/cpp': 'gcc',
    'virtual:compiler/fortran': 'gcc-gfortran',
    'virtual:compiler/rust': 'rust',
}

package_mapping['fedora'].update({
    'pkg:generic/openssl': 'openssl',
})
package_mapping['arch'].update({
    'pkg:generic/openssl': 'openssl',
})


# TODO: deal with -devel & co for build/host-requires


def read_pyproject(fname_sdist='./sdist/amended_sdist.tar.gz'):
    with tarfile.open(fname_sdist) as tar:
        fileobj_toml = None
        for info in tar.getmembers():
            name = info.name
            if '/' in name and name.split('/')[1] == 'pyproject.toml':
                fileobj_toml = tar.extractfile(info)
                break

        if fileobj_toml is None:
            raise ValueError(f"Could not read pyproject.toml file from sdist")
        
        tomldata = tomllib.load(fileobj_toml)
    return tomldata


def get_distro():
    for name in [distro.id(), distro.like()]:
        if name in package_manager.keys():
            return name

    warnings.warn(f'No support for distro {distro.id()} yet!')
    return 'fedora'


def get_package_manager():
    name = get_distro()
    return package_manager[name]
    

def print_toml_key(key, table):
    if key in table:
        print(f'[cyan]{key}[/] :')
        for item in table[key]:
            print(f'[bright_black]  {item}[/]')


def parse_external(show: bool = False, apply_mapping=False) -> list[str]:
    external_deps = []
    toml = read_pyproject()
    if 'external' in toml:
        external = toml['external']
        for key in ('build-requires', 'host-requires', 'dependencies'):
            if key in external:
                external_deps.extend(external[key])
                if show:
                    print_toml_key(key, external)

    for subkey in ('optional-build-requires', 'optional-host-requires', 'optional-dependencies'):
        key = f'external.{subkey}'
        if key in toml:
            if show:
                print_toml_key(key, toml[key])

    if apply_mapping:
        distro_name = get_distro()
        _mapping = package_mapping[distro_name]
        _mapped_deps = []
        for dep in external_deps:
            try:
                _mapped_deps.append(_mapping[dep])
            except KeyError:
                raise ValueError(f"Mapping entry for external dependency `{dep}` missing!")
        
        return _mapped_deps
    else:
        return external_deps


def main(package_name: str,
    external: Annotated[bool, typer.Option(help="Show external dependencies for package")] = False,
    system_install_cmd: Annotated[bool, typer.Option(
        help="Show install command with system package manager for `--pypi` and/or "
             "`--external` dependencies")] = False,
    ) -> None:
    """
    py-show: inspecting package dependencies
    """
    if external:
        parse_external(show=not system_install_cmd)

    if system_install_cmd:
        pkg_mgr = get_package_manager()
        install_cmd = package_mgr_install_commands[pkg_mgr]
        external_deps = parse_external(apply_mapping=True)
        _deps = ' '.join(external_deps)
        print(f"{install_cmd} {_deps}")



if __name__ == '__main__':
    typer.run(main)
