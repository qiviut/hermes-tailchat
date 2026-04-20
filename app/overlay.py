from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


def _git(repo_path: Path, *args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ['git', *args],
        cwd=repo_path,
        check=check,
        capture_output=True,
        text=True,
    )



def _git_stdout(repo_path: Path, *args: str) -> str:
    return (_git(repo_path, *args).stdout or '').strip()



def detect_upstream_ref(repo_path: Path) -> str | None:
    symbolic = _git_stdout(repo_path, 'symbolic-ref', 'refs/remotes/origin/HEAD')
    if symbolic.startswith('refs/remotes/'):
        return symbolic.removeprefix('refs/remotes/')
    for candidate in ('origin/main', 'origin/master'):
        if _git(repo_path, 'rev-parse', '--verify', candidate).returncode == 0:
            return candidate
    return None



def _clear_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for child in path.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()



def build_overlay_report(repo_path: str | Path, *, export_dir: str | Path | None = None) -> dict[str, Any]:
    repo = Path(repo_path).expanduser()
    if not repo.exists():
        return {'label': repo.name, 'path': str(repo), 'available': False}

    if _git(repo, 'rev-parse', '--git-dir').returncode != 0:
        return {'label': repo.name, 'path': str(repo), 'available': False, 'error': 'not a git repository'}

    branch = _git_stdout(repo, 'branch', '--show-current') or 'detached'
    status = _git_stdout(repo, 'status', '--short', '--branch')
    dirty = any(line and not line.startswith('##') for line in status.splitlines())
    untracked_files = [line[3:] for line in status.splitlines() if line.startswith('?? ')]
    untracked = len(untracked_files)
    upstream_ref = detect_upstream_ref(repo)
    head_rev = _git_stdout(repo, 'rev-parse', 'HEAD') or None

    ahead = behind = 0
    merge_base = None
    commit_range = None
    ahead_commits: list[dict[str, str]] = []
    if upstream_ref and _git(repo, 'rev-parse', '--verify', upstream_ref).returncode == 0:
        counts = _git_stdout(repo, 'rev-list', '--left-right', '--count', f'{upstream_ref}...HEAD')
        if counts:
            behind_str, ahead_str = counts.split()
            behind = int(behind_str)
            ahead = int(ahead_str)
        merge_base = _git_stdout(repo, 'merge-base', upstream_ref, 'HEAD') or None
        if merge_base and head_rev and merge_base != head_rev:
            commit_range = f'{merge_base}..HEAD'
            log_output = _git_stdout(repo, 'log', '--reverse', '--format=%H%x09%s', commit_range)
            ahead_commits = [
                {'commit': line.split('\t', 1)[0], 'subject': line.split('\t', 1)[1] if '\t' in line else ''}
                for line in log_output.splitlines()
                if line.strip()
            ]

    staged_diff = _git_stdout(repo, 'diff', '--cached', '--binary', '--no-ext-diff', 'HEAD')
    working_tree_diff = _git_stdout(repo, 'diff', '--binary', '--no-ext-diff', 'HEAD')

    report: dict[str, Any] = {
        'label': repo.name,
        'path': str(repo),
        'available': True,
        'branch': branch,
        'upstream_ref': upstream_ref,
        'dirty': dirty,
        'untracked_count': untracked,
        'untracked_files': untracked_files,
        'ahead': ahead,
        'behind': behind,
        'head_rev': head_rev,
        'merge_base': merge_base,
        'commit_range': commit_range,
        'ahead_commits': ahead_commits,
        'has_working_tree_diff': bool(working_tree_diff or untracked_files),
        'has_staged_diff': bool(staged_diff),
    }

    if export_dir is not None:
        export_root = Path(export_dir).expanduser()
        patches_dir = export_root / 'patches'
        _clear_directory(patches_dir)
        if commit_range:
            _git(repo, 'format-patch', '--quiet', '--output-directory', str(patches_dir), commit_range, check=True)
        working_tree_path = export_root / 'working-tree.diff'
        staged_path = export_root / 'staged.diff'
        report_path = export_root / 'overlay-report.json'
        export_root.mkdir(parents=True, exist_ok=True)
        working_tree_payload = working_tree_diff or ''
        if untracked_files:
            manifest = ''.join(f'# untracked: {path}\n' for path in untracked_files)
            working_tree_payload = working_tree_payload + ('\n' if working_tree_payload and not working_tree_payload.endswith('\n') else '') + manifest
        working_tree_path.write_text(working_tree_payload)
        staged_path.write_text((staged_diff or '') + ('\n' if staged_diff and not staged_diff.endswith('\n') else ''))
        report['export_dir'] = str(export_root)
        report['exported_patch_count'] = len(list(patches_dir.glob('*.patch')))
        report['patches_dir'] = str(patches_dir)
        report['working_tree_diff_path'] = str(working_tree_path)
        report['staged_diff_path'] = str(staged_path)
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
        report['report_path'] = str(report_path)

    return report
