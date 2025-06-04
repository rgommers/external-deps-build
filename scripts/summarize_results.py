import json
import subprocess
from datetime import datetime

import pandas as pd


def show_last_run_id():
    cmd = ['gh', 'run', 'list', '--limit', '1']
    run_data = subprocess.run(cmd, check=True, text=True).stdout
    return None  # Read ID field from terminal output - not captured


def load_data() -> pd.DataFrame:
    with open('results/jobs_first100.json', 'r') as f:
        data1 = json.load(f)

    with open('results/jobs_second48.json', 'r') as f:
        data2 = json.load(f)

    jobs = data1['jobs']
    jobs.extend(data2['jobs'])

    rows = []
    for job in jobs:
        package_name = job['name'].split(', ')[0]
        distro_name = job['name'].split(', ')[1]
        has_external_metadata = job['name'].split(', ')[2] == 'false'
        success = job['conclusion'] == 'success'
        start_time = datetime.strptime(job['started_at'][:-1], "%Y-%m-%dT%H:%M:%S")
        end_time = datetime.strptime(job['completed_at'][:-1], "%Y-%m-%dT%H:%M:%S")
        duration = end_time - start_time
        rows.append([package_name, distro_name, has_external_metadata, success, duration])

    df = pd.DataFrame(rows, columns=['package', 'distro', 'baseline', 'success', 'duration'])
    return df


def print_table_success_stats(df_distros: pd.DataFrame) -> None:
    df_res = df_distros[['distro', 'success']].groupby(['distro']).sum()
    df_res['success'] = df_res['success'].map(lambda x: f"{x}/37")
    print(df_res.to_markdown())


def print_table_durations(df_distros: pd.DataFrame) -> None:
    df2 = df_distros[df_distros['success']]
    df3 = df2[['package', 'duration']].sort_values(by='duration', ascending=False)
    df4 = df3.groupby('package').mean().sort_values(by='duration', ascending=False)
    df5 = df4.copy()
    df5['duration'] = df5['duration'].dt.seconds.apply(lambda sec: f"{sec//60}m {sec - 60*(sec//60)}s")

    print(df5.head(12).to_markdown())


def print_table_successes(df_distros: pd.DataFrame, df_downloads: pd.DataFrame) -> None:
    _df = df_distros.merge(df_downloads).sort_values(by='download_rank').drop(columns='duration')
    table = _df.pivot_table(columns='distro', index='package', values='success', sort=False)
    print(table.map(lambda x: ':heavy_check_mark:' if x else ':x:').to_markdown())
    assert(len(table) == 37)


def print_all(df_distros: pd.DataFrame, df_downloads: pd.DataFrame) -> None:
    print_table_success_stats(df_distros)
    print('\n')
    print_table_durations(df_distros)
    print('\n')
    print_table_successes(df_distros, df_downloads)


if __name__ == '__main__':
    # Retrieve data in JSON format from:
    #
    #   https://api.github.com/repos/rgommers/external-deps-build/actions/runs/6566027806/jobs?per_page=100
    #   https://api.github.com/repos/rgommers/external-deps-build/actions/runs/6566027806/jobs?per_page=100&page=2
    #
    # save them under results/, and then run this script

    df = load_data()
    df_baseline = df[df['baseline']].drop(columns='baseline')
    df_distros = df[~df['baseline']].drop(columns='baseline')
    df_downloads = pd.read_csv('pypi_top150_nonpure.txt', names=['package'])
    df_downloads['download_rank'] = df_downloads.index

    print_all(df_distros, df_downloads)

