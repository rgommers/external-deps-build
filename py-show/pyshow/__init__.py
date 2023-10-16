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

# For `rust` virtual package: make that provide `rustc` and `cargo`? Different
# across distros, e.g. Fedora install only `rustc` for the `rust` package,
# while Arch installs both of those.

def unidict(deps: str | list[str]) -> dict[str, list[str]]:
    """Use when build and run dependencies are the same"""
    if type(deps) == str:
        deps = [deps]
    return dict(build=deps, run=deps)


def devel_dict(deps: str | list[str]) -> dict[str, list[str]]:
    """Use when build dep equals run dependencies plus `-devel`"""
    if type(deps) == str:
        deps = [deps]

    #build_deps = deps.copy()
    #build_deps.extend([s+'-devel' for s in deps])
    #return dict(run=deps, build=build_deps)
    return dict(run=deps, build=[s+'-devel' for s in deps])


# For external dependencies; for Python/PyPI ones we will make use of existing
# metadata files that distros already have.
package_mapping = {}
package_mapping['fedora'] = {
    'virtual:compiler/c': unidict('gcc'),
    'virtual:compiler/cpp': unidict('gcc-c++'),
    'virtual:compiler/fortran': unidict('gcc-gfortran'),
    'virtual:compiler/rust': unidict(['rust', 'cargo']),
}

package_mapping['arch'] = {
    'virtual:compiler/c': unidict('gcc'),
    'virtual:compiler/cpp': unidict('gcc'),
    'virtual:compiler/fortran': unidict('gcc-gfortran'),
    'virtual:compiler/rust': unidict('rust'),
}

package_mapping['fedora'].update({
    'pkg:generic/freetype': devel_dict('freetype'),
    'pkg:generic/lcms2': devel_dict('lcms2'),
    'pkg:generic/libffi': devel_dict('libffi'),
    'pkg:generic/libimagequant': devel_dict('libimagequant'),
    'pkg:generic/libjpeg': devel_dict('libjpeg-turbo'),
    'pkg:generic/libraqm': devel_dict('libraqm'),
    'pkg:generic/libtiff': devel_dict('libtiff'),
    'pkg:generic/libxcb': devel_dict('libxcb'),
    'pkg:generic/libxml2': devel_dict('libxml2'),
    'pkg:generic/libxslt': devel_dict('libxslt'),
    'pkg:generic/libyaml': devel_dict('libyaml'),
    'pkg:generic/libwebp': devel_dict('libwebp'),
    'pkg:generic/openjpeg': devel_dict('openjpeg2'),
    'pkg:generic/openssl': devel_dict('openssl'),
    'pkg:generic/tk': devel_dict('tk'),
    'pkg:generic/zlib': devel_dict('zlib'),
})
package_mapping['arch'].update({
    'pkg:generic/freetype': unidict('freetype2'),
    'pkg:generic/lcms2': unidict('lcms2'),
    'pkg:generic/libffi': unidict('libffi'),
    'pkg:generic/libimagequant': unidict('libimagequant'),
    'pkg:generic/libjpeg': unidict('libjpeg-turbo'),
    'pkg:generic/libraqm': unidict('libraqm'),
    'pkg:generic/libtiff': unidict('libtiff4'),  # separate in Arch, libtiff exists too
    'pkg:generic/libxcb': unidict('libxcb'),
    'pkg:generic/libxml2': unidict('libxml2'),
    'pkg:generic/libxslt': unidict('libxslt'),
    'pkg:generic/libyaml': unidict('libyaml'),
    'pkg:generic/libwebp': unidict('libwebp'),
    'pkg:generic/openjpeg': unidict('openjpeg2'),
    'pkg:generic/openssl': unidict('openssl'),
    'pkg:generic/tk': unidict('tk'),
    'pkg:generic/zlib': unidict('zlib'),
})


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


def parse_external(show: bool = False, apply_mapping=False) -> list[str]:
    """Adds optional build/host deps in 'extra' by default, because those are typically desired"""
    external_build_deps = []
    external_run_deps = []
    toml = read_pyproject()
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

    if apply_mapping:
        distro_name = get_distro()
        _mapping = package_mapping[distro_name]
        _mapped_deps = []
        for dep in external_build_deps:
            try:
                _mapped_deps.extend(_mapping[dep]['build'])
            except KeyError:
                raise ValueError(f"Mapping entry for external dependency `{dep}` missing!")
        
        for dep in external_run_deps:
            try:
                _mapped_deps.extend(_mapping[dep]['run'])
            except KeyError:
                raise ValueError(f"Mapping entry for external dependency `{dep}` missing!")
        return _mapped_deps
    else:
        all_deps = external_build_deps.copy()
        all_deps.extend(external_run_deps)
        return


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
