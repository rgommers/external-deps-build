import logging
import shlex
import tarfile
import tomllib
from functools import cache
from pathlib import Path
from typing import Annotated

import distro
import typer
from rich import print as rprint
from rich.console import Console
from rich.logging import RichHandler
from external_metadata_mappings import Ecosystems, Registry, Mapping


HERE = Path(__file__).parent
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(console=Console(stderr=True))],
)
log = logging.getLogger(__name__)


@cache
def get_known_ecosystems() -> Mapping:
    return Ecosystems.from_url(
        "https://raw.githubusercontent.com/jaimergp/external-metadata-mappings/"
        "refs/heads/main/data/known-ecosystems.json"
    )


@cache
def get_remote_mapping(ecosystem_or_url: str) -> Mapping:
    if ecosystem_or_url.startswith(("http:", "https:")):
        url = ecosystem_or_url
    else:
        url = (
            "https://raw.githubusercontent.com/jaimergp/external-metadata-mappings/"
            f"refs/heads/main/data/{ecosystem_or_url}.mapping.json"
        )
    return Mapping.from_url(url)


@cache
def get_remote_registry() -> Registry:
    return Registry.from_url(
        "https://raw.githubusercontent.com/jaimergp/external-metadata-mappings/"
        "refs/heads/main/data/registry.json"
    )


def validate_purl(purl):
    reg = get_remote_registry()
    if purl not in reg.iter_unique_purls():
        log.warning(f"PURL {purl} is not recognized in the central registry.")
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
        log.warning(msg)


def read_pyproject(package_name: str, sdist_dir: str | Path | None = None):
    if sdist_dir is None:
        # assume editable install
        sdist_dir = HERE / "../../sdist/_amended/"
    else:
        sdist_dir = Path(sdist_dir)
    fname_sdist = None
    for name in (package_name, package_name.replace("-", "_"), package_name.replace("_", "-")):
        tarballs = sorted(sdist_dir.glob(f"{name}-*.tar.gz"))
        if tarballs:
            if len(tarballs) > 1:
                log.warning("More than one sdist found; choosing latest one")
            fname_sdist = tarballs[-1]
            break
    if fname_sdist is None:
        raise ValueError(f"Couldn't find sdist for {package_name} at {sdist_dir}")

    with tarfile.open(fname_sdist) as tar:
        fileobj_toml = None
        for info in tar.getmembers():
            name = info.name
            if "/" in name and name.split("/")[1] == "pyproject.toml":
                fileobj_toml = tar.extractfile(info)
                break

        if fileobj_toml is None:
            raise ValueError("Could not read pyproject.toml file from sdist")

        tomldata = tomllib.load(fileobj_toml)
    return tomldata


def get_distro():
    for name in [distro.id(), distro.like()]:
        if name == "darwin":
            return "homebrew"
        elif name in distro_to_package_manager.keys():
            return name

    log.warning(f"No support for distro {distro.id()} yet!")
    # FIXME
    return "fedora"


def print_toml_key(key, table):
    if key in table:
        rprint(f"[cyan]{key}[/]:")
        if isinstance(table[key], list):
            for item in table[key]:
                rprint(f"[bright_black]  {item}[/]")
        elif isinstance(table[key], dict):
            for key2 in table[key]:
                rprint(f"  [bright_black]{key2}[/]:")
                for item in table[key][key2]:
                    rprint(f"[bright_black]    {item}[/]")


def _get_mapped_spec(
    dep, mapping, package_manager, registry, specs_type="run", optional: bool = False
):
    try:
        return next(
            iter(
                mapping.iter_specs_by_id(
                    dep,
                    package_manager,
                    specs_type=specs_type,
                    resolve_alias_with_registry=registry,
                    only_mapped=True,
                )
            )
        )
    except (StopIteration, ValueError) as exc:
        msg = f"mapping entry for external build dependency `{dep}` missing!"
        if optional:
            log.info(f"optional {msg}")
            return ()
        else:
            raise ValueError(msg) from exc


def parse_external(
    package_name: str,
    show: bool = False,
    apply_mapping_for: str | None = None,
    distro_name: str = None,
    sdist_dir: str | Path | None = None,
) -> list[str]:
    """Adds optional build/host deps in 'extra' by default, because those are typically desired"""
    external_build_deps = []
    optional_external_build_deps = []
    external_run_deps = []
    optional_external_run_deps = []
    toml = read_pyproject(package_name, sdist_dir=sdist_dir)
    if "external" in toml:
        external = toml["external"]
        for key in ("build-requires", "host-requires", "dependencies"):
            if key in external:
                if "requires" in key:
                    external_build_deps.extend(external[key])
                else:
                    external_run_deps.extend(external[key])
                if show:
                    print_toml_key(key, external)

        for key in ("optional-build-requires", "optional-host-requires", "optional-dependencies"):
            if key in external:
                if "requires" in key:
                    optional_external_build_deps.extend(external[key]["extra"])
                else:
                    optional_external_run_deps.extend(external[key]["extra"])
                if show:
                    print_toml_key(key, external)

    if not apply_mapping_for:
        all_deps = external_build_deps.copy()
        all_deps.extend(external_run_deps)
        return list(dict.fromkeys(all_deps))
    else:
        if distro_name is None:
            distro_name = get_distro()
        _mapping = get_remote_mapping(distro_name)
        _mapped_deps = []
        _registry = get_remote_registry()
        for depgroup, specs_type, optional in (
            (external_build_deps, ("build", "host"), False),
            (optional_external_build_deps, ("build", "host"), True),
            (external_run_deps, "run", False),
            (optional_external_run_deps, "run", True),
        ):
            for dep in depgroup:
                _mapped_deps.extend(
                    _get_mapped_spec(
                        dep,
                        mapping=_mapping,
                        package_manager=apply_mapping_for,
                        specs_type=specs_type,
                        registry=_registry,
                        optional=optional,
                    )
                )

        if _uses_c_cpp_compiler(external_build_deps):
            # TODO: handling of non-default Python installs isn't done here,
            # this adds the python-dev/devel package corresponding to the
            # default Python version of the distro.
            _mapped_deps.extend(get_python_dev(distro_name))

        return list(dict.fromkeys(_mapped_deps))


def _uses_c_cpp_compiler(external_build_deps: list[str]) -> bool:
    for compiler in ("dep:virtual/compiler/c", "dep:virtual/compiler/cpp"):
        if compiler in external_build_deps:
            return True
    return False


def get_python_dev(distro_name) -> list[str]:
    """Return the python development package to list of dependencies

    This is an implicit dependency for packages that use a C or C++ compiler to
    build Python extension modules.
    """
    _mapping = get_remote_mapping(distro_name)
    return next(iter(_mapping.iter_by_id("dep:generic/python")))["specs"]["build"]


# This should be a registration mechanism - it's here now for demo purposes.
distro_to_package_manager = {
    "arch": "pacman",
    "fedora": "dnf",
    "ubuntu": "apt-get",
    "conda-forge": "mamba",
    "darwin": "brew",
}
package_manager_to_distro = {v: k for k, v in distro_to_package_manager.items()}


def main(
    package_name: str,
    external: Annotated[bool, typer.Option(help="Show external dependencies for package")] = False,
    validate: Annotated[
        bool, typer.Option(help="Validate external dependencies against central registry")
    ] = False,
    system_install_cmd: Annotated[
        bool,
        typer.Option(
            help="Show install command with system package manager for `--pypi` and/or "
            "`--external` dependencies"
        ),
    ] = False,
    package_manager: Annotated[
        str, typer.Option(help="If given, use this package manager rather than auto-detect one")
    ] = "",
    sdist_dir: Annotated[
        str | None, typer.Option(help="Directory where amended sdists are located")
    ] = None,
) -> None:
    """
    py-show: inspecting package dependencies
    """
    if external:
        purls = parse_external(package_name, show=not system_install_cmd, sdist_dir=sdist_dir)
        if purls and validate:
            for purl in purls:
                validate_purl(purl)

    ecosystems = get_known_ecosystems()
    distro_name = None
    if package_manager:
        for name, details in ecosystems["ecosystems"].items():
            mapping = get_remote_mapping(details["mapping"])
            for package_manager_details in mapping["package_managers"]:
                if package_manager == package_manager_details["name"]:
                    distro_name = name
                    break
            if distro_name is not None:
                break
    if distro_name is None:
        distro_name = get_distro()
        mapping = get_remote_mapping(ecosystems["ecosystems"][distro_name]["mapping"])
        package_manager = mapping["package_managers"][0]["name"]

    if system_install_cmd:
        mapping = get_remote_mapping(distro_name)
        package_manager = mapping.get_package_manager(package_manager)
        external_deps = parse_external(
            package_name,
            apply_mapping_for=package_manager["name"],
            distro_name=distro_name,
            sdist_dir=sdist_dir,
        )
        cmd = mapping.build_install_command(package_manager, external_deps)
        # print(shlex.join(cmd))
        print(" ".join(cmd))


def entry_point():
    typer.run(main)


if __name__ == "__main__":
    entry_point()
