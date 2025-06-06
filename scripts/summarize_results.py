# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pandas",
#   "requests",
#   "tabulate",
# ]
# ///
# `gh` (Github's official CLI) is also a dependency

import os
import re
import json
import subprocess
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

REPO_ROOT = Path(__file__).parent.parent

def last_run_id() -> int:
    cmd = [
        "gh",
        "run",
        "list",
        "--branch=main",
        "--workflow=build_all.yml",
        "--limit=1",
        "--json=databaseId",
        "--jq=.[].databaseId",
    ]
    return int(subprocess.run(cmd, check=True, text=True, capture_output=True).stdout)


def download_latest_gha_run_data(run_id: int, token: str) -> list[dict]:
    url = f"https://api.github.com/repos/rgommers/external-deps-build/actions/runs/{run_id}/jobs"
    data = []
    for page in (1, 2):
        r = requests.get(
            f"{url}?per_page=100&page={page}",
            headers={
                "X-GitHub-Api-Version":"2022-11-28",
                "Authorization": f"Bearer {token}",
            }
        )
        r.raise_for_status()
        data += r.json()["jobs"]
    return data


def load_data() -> pd.DataFrame:
    if token := os.environ.get("GH_TOKEN"):
        jobs = download_latest_gha_run_data(last_run_id(), token)
        (REPO_ROOT / "results" / "jobs_first100.json").write_text(json.dumps({"jobs": jobs[:100]}))
        (REPO_ROOT / "results" / "jobs_second48.json").write_text(json.dumps({"jobs": jobs[100:]}))
    else:
        data1 = json.loads((REPO_ROOT / "results" / "jobs_first100.json").read_text())
        data2 = json.loads((REPO_ROOT / "results" / "jobs_second48.json").read_text())
        jobs = data1['jobs']
        jobs.extend(data2['jobs'])

    rows = []
    for job in jobs:
        name_fields = job['name'].split(', ')
        if len(name_fields) == 3:
            package_name, distro_name, has_external_metadata = name_fields
            has_external_metadata = has_external_metadata == "false"
        elif len(name_fields) == 2:
            continue  # these are the smoke tests
        success = job['conclusion'] == 'success'
        start_time = datetime.strptime(job['started_at'][:-1], "%Y-%m-%dT%H:%M:%S")
        end_time = datetime.strptime(job['completed_at'][:-1], "%Y-%m-%dT%H:%M:%S")
        duration = end_time - start_time
        rows.append([package_name, distro_name, has_external_metadata, success, duration])

    df = pd.DataFrame(rows, columns=['package', 'distro', 'baseline', 'success', 'duration'])
    return df


def table_success_stats(df_distros: pd.DataFrame) -> str:
    df_res = df_distros[['distro', 'success']].groupby(['distro']).sum()
    df_res['success'] = df_res['success'].map(lambda x: f"{x}/37")
    return df_res.to_markdown()


def table_durations(df_distros: pd.DataFrame) -> str:
    df2 = df_distros[df_distros['success']]
    df3 = df2[['package', 'duration']].sort_values(by='duration', ascending=False)
    df4 = df3.groupby('package').mean().sort_values(by='duration', ascending=False)
    df5 = df4.copy()
    df5['duration'] = df5['duration'].dt.seconds.apply(lambda sec: f"{sec//60}m {sec - 60*(sec//60)}s")

    return df5.head(12).to_markdown()


def table_successes(df_distros: pd.DataFrame, df_downloads: pd.DataFrame) -> str:
    _df = df_distros.merge(df_downloads).sort_values(by='download_rank').drop(columns='duration')
    table = _df.pivot_table(columns='distro', index='package', values='success', sort=False)
    assert len(table) == 37
    return table.map(lambda x: ':heavy_check_mark:' if x else ':x:').to_markdown()


def print_all(df_distros: pd.DataFrame, df_downloads: pd.DataFrame) -> None:
    print("Overall number of successful builds per distro:\n")
    print(table_success_stats(df_distros))
    print('\n')
    print("Average CI job duration per package for the heaviest builds:\n")
    print(table_durations(df_distros))
    print('\n')
    print("Per-package success/failure:\n")
    print(table_successes(df_distros, df_downloads))


def update_readme(df_distros, df_downloads) -> None:
    readme = Path(__file__).parent.parent / "README.md"
    readme_text = readme.read_text()
    readme_text = re.sub(
        "<!-- DISTRO_TABLE -->(.*)<!-- /DISTRO_TABLE -->", 
        f"<!-- DISTRO_TABLE -->\n{table_success_stats(df_distros)}\n<!-- /DISTRO_TABLE -->", 
        readme_text, 
        flags=re.MULTILINE | re.DOTALL,
    )
    readme_text = re.sub(
        "<!-- DURATION_TABLE -->(.*)<!-- /DURATION_TABLE -->", 
        f"<!-- DURATION_TABLE -->\n{table_durations(df_distros)}\n<!-- /DURATION_TABLE -->", 
        readme_text, 
        flags=re.MULTILINE | re.DOTALL,
    )
    readme_text = re.sub(
        "<!-- SUCCESS_TABLE -->(.*)<!-- /SUCCESS_TABLE -->", 
        f"<!-- SUCCESS_TABLE -->\n{table_successes(df_distros, df_downloads)}\n<!-- /SUCCESS_TABLE -->", 
        readme_text, 
        flags=re.MULTILINE | re.DOTALL,
    )
    readme.write_text(readme_text)


if __name__ == '__main__':
    df = load_data()
    df_baseline = df[df['baseline']].drop(columns='baseline')
    df_distros = df[~df['baseline']].drop(columns='baseline')
    df_downloads = pd.read_csv('top_packages/pypi_top150_nonpure.txt', names=['package'])
    df_downloads['download_rank'] = df_downloads.index

    update_readme(df_distros, df_downloads)
    print_all(df_distros, df_downloads)
