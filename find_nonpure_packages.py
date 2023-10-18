import json

from pypi_json import PyPIJSON


def is_pure(package_name):
    with PyPIJSON() as client:
        metadata = client.get_metadata(package_name)

    tags_mapping = metadata.get_wheel_tag_mapping()
    if len(tags_mapping) < 2:
        raise ValueError(f"{package_name}: has no sdist or no wheel - verify this manually")

    _has_an_sdist = False
    _has_a_platform_wheel = False
    for item in tags_mapping:
        if isinstance(item, list):  # sdist
            if len(item) == 1:
                _fname = str(item[0])
                if _fname.endswith('tar.gz'):
                    _has_an_sdist = True
                elif not _fname.endswith('.zip'):
                    # If it only has a .zip, that's old-style and we don't
                    # handle that in the sdist patching, so skip package
                    print('Unexpected file extension for package: ', _fname)
        else:  # wheel
            try:
                tag = list(item.keys())[0]
            except IndexError:
                print('No wheels found for package: ', pkgname)
                continue
            if str(tag).endswith('py3-none-any'):
                return True
            _has_a_platform_wheel = True

    if _has_a_platform_wheel and _has_an_sdist:
        return False
    else:
        # Unknown actually, so skip these packages
        return True


with open('top-pypi-packages-30-days.json') as f:
    data_top100 = json.load(f)['rows'][:150]
    pkgnames = [row['project'] for row in data_top100]


pure_pkgs = []
nonpure_pkgs = []
for pkgname in pkgnames:
    if is_pure(pkgname):
        pure_pkgs.append(pkgname)
    else:
        nonpure_pkgs.append(pkgname)

with open('pypi_top100_pure.txt', 'w') as f:
    for pkg in pure_pkgs:
        f.write(pkg + '\n')


with open('pypi_top100_nonpure.txt', 'w') as f:
    for pkg in nonpure_pkgs:
        f.write(pkg + '\n')
