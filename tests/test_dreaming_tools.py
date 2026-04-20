from __future__ import annotations

import json
import subprocess
from pathlib import Path

from app.dreaming import (
    build_analysis_candidates,
    build_dream_report,
    build_retrieval_index,
    extract_reflection_windows,
    filter_recent_sessions,
    render_motd,
)
from app.overlay import build_overlay_report
from app.retry_policy import can_auto_retry_error, is_rate_limited_error


NOW = 2_000_000_000.0



def make_session(*, session_id: str = 's1', started_at: float = NOW - 600, ended_at: float | None = None, title: str = 'Recent chat', messages: list[dict] | None = None) -> dict:
    return {
        'id': session_id,
        'title': title,
        'started_at': started_at,
        'ended_at': ended_at,
        'messages': messages or [],
    }



def assistant_tool_call(name: str, arguments: str, *, timestamp: float = NOW - 300) -> dict:
    return {
        'role': 'assistant',
        'content': '',
        'timestamp': timestamp,
        'tool_calls': [
            {
                'type': 'function',
                'function': {
                    'name': name,
                    'arguments': arguments,
                },
            }
        ],
    }



def test_build_dream_report_skips_when_everything_is_idle() -> None:
    sessions = [
        make_session(
            session_id='old',
            started_at=NOW - 10_000,
            ended_at=NOW - 7_200,
            title='Old chat',
            messages=[{'role': 'user', 'content': 'hello', 'timestamp': NOW - 7_200}],
        )
    ]

    report = build_dream_report(sessions, now_ts=NOW, lookback_seconds=86_400, max_idle_seconds=3_600)

    assert report['status'] == 'skipped'
    assert report['recent_activity']['idle_seconds'] == 7_200
    assert report['recent_activity']['last_session_id'] == 'old'



def test_filter_recent_sessions_and_skip_gate_keep_old_sessions_out_of_windows() -> None:
    sessions = [
        make_session(
            session_id='recent',
            started_at=NOW - 500,
            title='Recent chat',
            messages=[assistant_tool_call('skill_view', '{"name": "recent-skill"}', timestamp=NOW - 490)],
        ),
        make_session(
            session_id='old',
            started_at=NOW - 10_000,
            ended_at=NOW - 7_200,
            title='Old chat',
            messages=[assistant_tool_call('skill_manage', '{"action": "patch", "name": "old-skill"}', timestamp=NOW - 7_200)],
        ),
    ]

    recent_sessions = filter_recent_sessions(sessions, now_ts=NOW, lookback_seconds=3_600)
    assert [session['id'] for session in recent_sessions] == ['recent']

    skipped_report = build_dream_report(sessions, now_ts=NOW, lookback_seconds=3_600, max_idle_seconds=60)
    assert skipped_report['status'] == 'skipped'
    assert extract_reflection_windows(recent_sessions)
    skipped_windows = extract_reflection_windows(recent_sessions) if skipped_report['status'] == 'ready' else []
    assert skipped_windows == []



def test_build_dream_report_tracks_skills_and_memory_separately() -> None:
    sessions = [
        make_session(
            messages=[
                {'role': 'user', 'content': 'please improve the skill', 'timestamp': NOW - 500},
                assistant_tool_call('skill_view', '{"name": "hermes-agent"}'),
                assistant_tool_call('skill_manage', '{"action": "patch", "name": "hermes-agent"}', timestamp=NOW - 299),
                assistant_tool_call('memory', '{"action": "add", "target": "memory", "content": "useful fact"}', timestamp=NOW - 298),
                assistant_tool_call('session_search', '{"query": "hermes OR memory"}', timestamp=NOW - 297),
            ],
        )
    ]

    report = build_dream_report(sessions, now_ts=NOW, lookback_seconds=86_400, max_idle_seconds=3_600)

    assert report['status'] == 'ready'
    assert report['usage']['skill_view_calls'] == 1
    assert report['usage']['skill_manage_calls'] == 1
    assert report['usage']['memory_calls'] == 1
    assert report['usage']['memory_actions']['add'] == 1
    assert report['usage']['session_search_calls'] == 1
    assert report['usage']['top_skills'][0] == {'count': 2, 'name': 'hermes-agent'}
    assert report['usage']['signal_sessions'][0] == {'session_id': 's1', 'count': 4}



def test_extract_reflection_windows_keeps_local_context_for_skill_and_memory_events() -> None:
    sessions = [
        make_session(
            messages=[
                {'role': 'user', 'content': 'please use the hermes-agent skill', 'timestamp': NOW - 500},
                assistant_tool_call('skill_view', '{"name": "hermes-agent"}'),
                {'role': 'tool', 'tool_name': 'skill_view', 'content': '{"ok": true}', 'timestamp': NOW - 499},
                {'role': 'assistant', 'content': 'I found the skill.', 'timestamp': NOW - 498},
                assistant_tool_call('memory', '{"action": "replace", "target": "memory", "old_text": "old", "content": "new"}'),
                {'role': 'user', 'content': 'that memory update was correct', 'timestamp': NOW - 497},
            ],
        )
    ]

    windows = extract_reflection_windows(sessions, before=1, after=2)

    assert [window['tool_name'] for window in windows] == ['skill_view', 'memory']
    assert windows[0]['messages'][0]['content'] == 'please use the hermes-agent skill'
    assert windows[1]['messages'][-1]['content'] == 'that memory update was correct'
    assert windows[0]['window_id'] == 's1:1:skill_view'
    assert windows[1]['signal_count_in_session'] == 2



def test_analysis_candidates_prioritize_patches_memory_churn_and_dense_sessions() -> None:
    sessions = [
        make_session(
            session_id='s1',
            title='Patch-heavy chat',
            messages=[
                {'role': 'user', 'content': 'load the skill then patch it', 'timestamp': NOW - 500},
                assistant_tool_call('skill_view', '{"name": "hermes-agent"}', timestamp=NOW - 499),
                assistant_tool_call('skill_manage', '{"action": "patch", "name": "hermes-agent"}', timestamp=NOW - 498),
                assistant_tool_call('memory', '{"action": "replace", "target": "memory", "old_text": "old", "content": "new"}', timestamp=NOW - 497),
                {'role': 'assistant', 'content': 'all updated', 'timestamp': NOW - 496},
            ],
        ),
        make_session(
            session_id='s2',
            title='Recall chat',
            messages=[
                {'role': 'user', 'content': 'remember what happened last time', 'timestamp': NOW - 400},
                assistant_tool_call('session_search', '{"query": "hermes OR skill"}', timestamp=NOW - 399),
            ],
        ),
    ]
    previous_report = {
        'generated_at': '2026-04-18T00:00:00+00:00',
        'status': 'ready',
        'usage': {
            'skill_view_calls': 0,
            'skill_manage_calls': 0,
            'memory_calls': 0,
            'session_search_calls': 0,
        },
    }

    report = build_dream_report(sessions, now_ts=NOW, lookback_seconds=86_400, max_idle_seconds=3_600)
    windows = extract_reflection_windows(sessions)
    analysis = build_analysis_candidates(report, windows, previous_report=previous_report)

    assert analysis['deltas']['skill_manage_calls'] == 1
    assert analysis['summary']['memory_churn'] == {'replace': 1}
    assert analysis['window_candidates'][0]['tool_name'] == 'skill_manage'
    assert 'review recently patched skills first' in analysis['summary']['focus']
    assert analysis['session_candidates'][0]['session_id'] == 's1'



def test_retrieval_index_builds_mode_specific_bundles_from_dream_artifacts_context_and_logs() -> None:
    sessions = [
        make_session(
            session_id='s1',
            title='Patch-heavy chat',
            messages=[
                {'role': 'user', 'content': 'load the skill then patch it', 'timestamp': NOW - 500},
                assistant_tool_call('skill_view', '{"name": "hermes-agent"}', timestamp=NOW - 499),
                assistant_tool_call('skill_manage', '{"action": "patch", "name": "hermes-agent"}', timestamp=NOW - 498),
                assistant_tool_call('memory', '{"action": "replace", "target": "memory", "old_text": "old", "content": "new"}', timestamp=NOW - 497),
                assistant_tool_call('session_search', '{"query": "dreaming OR memory"}', timestamp=NOW - 496),
            ],
        )
    ]
    report = build_dream_report(
        sessions,
        now_ts=NOW,
        lookback_seconds=86_400,
        max_idle_seconds=3_600,
        state_dir='/tmp/hermes-dream',
    )
    windows = extract_reflection_windows(sessions)
    analysis = build_analysis_candidates(report, windows)
    retrieval = build_retrieval_index(
        report,
        windows,
        analysis,
        context_files=[
            '/repo/AGENTS.md',
            '/repo/docs/design/2026-04-19-hermes-memory-hierarchy-and-frame-of-mind-retrieval.md',
        ],
        log_files=['/tmp/hermes-dream/runs.jsonl'],
    )

    assert retrieval['source_count'] >= 7
    assert 'overlay-report' in retrieval['modes']['operator']['source_ids']
    assert 'dream-runs-log' in retrieval['modes']['operator']['source_ids']
    assert 'reflection-windows' in retrieval['modes']['reflection']['source_ids']
    assert 'analysis-candidates' in retrieval['modes']['reflection']['source_ids']
    assert 'context-1' in retrieval['modes']['coding']['source_ids']
    assert retrieval['modes']['operator']['source_ids'] != retrieval['modes']['reflection']['source_ids']
    assert retrieval['modes']['conversational']['estimated_tokens'] < retrieval['modes']['reflection']['estimated_tokens']



def test_render_motd_mentions_report_paths_recent_signals_and_analysis_queue() -> None:
    report = {
        'generated_at': '2026-04-18T05:12:00Z',
        'status': 'ready',
        'recent_activity': {
            'idle_seconds': 900,
            'last_session_id': 's1',
            'last_title': 'Recent chat',
        },
        'usage': {
            'skill_view_calls': 2,
            'skill_manage_calls': 1,
            'memory_calls': 1,
            'top_skills': [{'name': 'hermes-agent', 'count': 2}],
            'memory_actions': {'add': 1},
        },
        'paths': {
            'state_dir': '/tmp/hermes-dream',
            'latest_summary': '/tmp/hermes-dream/latest-summary.json',
            'windows': '/tmp/hermes-dream/windows.json',
            'analysis_candidates': '/tmp/hermes-dream/analysis-candidates.json',
            'retrieval_index': '/tmp/hermes-dream/retrieval-index.json',
            'overlay_report': '/tmp/hermes-dream/overlay-report.json',
            'runs_log': '/tmp/hermes-dream/runs.jsonl',
        },
        'overlay': {
            'label': 'hermes-agent',
            'branch': 'main',
            'upstream_ref': 'origin/main',
            'dirty': False,
            'ahead': 2,
            'behind': 0,
            'exported_patch_count': 2,
        },
    }
    analysis = {
        'summary': {
            'candidate_window_count': 3,
            'candidate_session_count': 1,
            'focus': ['review recently patched skills first', 'inspect high-frequency skills for overuse or missing coverage'],
        }
    }

    motd = render_motd(report, analysis=analysis)

    assert 'Hermes summary' in motd
    assert 'top skill: hermes-agent (2)' in motd
    assert '/tmp/hermes-dream/latest-summary.json' in motd
    assert '/tmp/hermes-dream/retrieval-index.json' in motd
    assert 'overlay: hermes-agent main vs origin/main +2/-0 clean patches=2' in motd
    assert 'dream queue: windows=3 sessions=1' in motd



def test_overlay_report_exports_patch_series_and_diffs(tmp_path: Path) -> None:
    remote = tmp_path / 'remote.git'
    repo = tmp_path / 'repo'
    export_dir = tmp_path / 'export'
    subprocess.run(['git', 'init', '--bare', str(remote)], check=True)
    subprocess.run(['git', 'clone', str(remote), str(repo)], check=True)
    subprocess.run(['git', 'config', 'user.email', 'dream@example.com'], cwd=repo, check=True)
    subprocess.run(['git', 'config', 'user.name', 'Dream Tester'], cwd=repo, check=True)
    (repo / 'README.md').write_text('base\n')
    subprocess.run(['git', 'add', 'README.md'], cwd=repo, check=True)
    subprocess.run(['git', 'commit', '-m', 'base commit'], cwd=repo, check=True)
    subprocess.run(['git', 'push', '-u', 'origin', 'HEAD:main'], cwd=repo, check=True)
    subprocess.run(['git', 'branch', '--set-upstream-to=origin/main', 'master'], cwd=repo, check=True)
    (repo / 'README.md').write_text('base\nlocal change\n')
    subprocess.run(['git', 'commit', '-am', 'local overlay commit'], cwd=repo, check=True)
    (repo / 'scratch.txt').write_text('uncommitted\n')

    report = build_overlay_report(repo, export_dir=export_dir)

    assert report['available'] is True
    assert report['ahead'] == 1
    assert report['upstream_ref'] == 'origin/main'
    assert report['exported_patch_count'] == 1
    assert report['has_working_tree_diff'] is True
    assert len(report['ahead_commits']) == 1
    assert (export_dir / 'patches').exists()
    assert len(list((export_dir / 'patches').glob('*.patch'))) == 1
    assert 'scratch.txt' in (export_dir / 'working-tree.diff').read_text()
    saved = json.loads((export_dir / 'overlay-report.json').read_text())
    assert saved['ahead'] == 1



def test_retry_policy_never_auto_retries_rate_limit_errors() -> None:
    assert is_rate_limited_error('429 rate limit; retry after 30s')
    assert not can_auto_retry_error('429 rate limit; retry after 30s')
    assert can_auto_retry_error('503 service unavailable; try again')
