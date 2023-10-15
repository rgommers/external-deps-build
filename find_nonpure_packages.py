import json

from pypi_json import PyPIJSON


def is_pure(package_name):
    with PyPIJSON() as client:
        metadata = client.get_metadata(package_name)

    tags_mapping = metadata.get_wheel_tag_mapping()
    if len(tags_mapping) < 2:
        raise ValueError(f"{package_name}: has no sdist or no wheel - verify this manually")

    for item in tags_mapping:
        if isinstance(item, list):  # sdist
            assert len(item) == 1 and str(item[0]).endswith('tar.gz')
        else:  # wheel
            try:
                tag = list(item.keys())[0]
            except IndexError:
                print(pkgname)
                print(item)
            if str(tag).endswith('py3-none-any'):
                return True
    return False


with open('top-pypi-packages-30-days.json') as f:
    data_top100 = json.load(f)['rows'][:100]
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
