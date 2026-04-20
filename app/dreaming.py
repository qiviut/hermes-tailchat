from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_SIGNAL_TOOLS = {'skill_view', 'skill_manage', 'memory', 'session_search'}
_MODE_RULES = {
    'coding': {
        'keywords': ('implement', 'fix', 'refactor', 'test', 'debug', 'review', 'code', 'diff'),
        'preferred_tags': ('coding', 'context', 'summary', 'analysis'),
        'avoid_tags': ('log',),
        'max_sources': 4,
    },
    'operator': {
        'keywords': ('deploy', 'restart', 'status', 'service', 'timer', 'log', 'overlay', 'tailscale', 'systemd'),
        'preferred_tags': ('operator', 'summary', 'overlay', 'log', 'context'),
        'avoid_tags': (),
        'max_sources': 4,
    },
    'reflection': {
        'keywords': ('memory', 'skill', 'dream', 'audit', 'compress', 'improve', 'stale', 'contradiction', 'retrieval'),
        'preferred_tags': ('reflection', 'analysis', 'windows', 'summary', 'context'),
        'avoid_tags': (),
        'max_sources': 6,
    },
    'conversational': {
        'keywords': ('explain', 'compare', 'should', 'support', 'what', 'why', 'help'),
        'preferred_tags': ('conversational', 'summary', 'context', 'analysis'),
        'avoid_tags': ('log',),
        'max_sources': 3,
    },
}

_WINDOW_BASE_SCORES = {
    'skill_view': 2,
    'skill_manage': 7,
    'memory': 4,
    'session_search': 3,
}


def _safe_json_loads(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}



def session_last_activity(session: dict[str, Any]) -> float | None:
    values: list[float] = []
    for key in ('started_at', 'ended_at'):
        value = session.get(key)
        if isinstance(value, (int, float)):
            values.append(float(value))
    for message in session.get('messages') or []:
        timestamp = message.get('timestamp')
        if isinstance(timestamp, (int, float)):
            values.append(float(timestamp))
    return max(values) if values else None



def filter_recent_sessions(sessions: list[dict[str, Any]], *, now_ts: float, lookback_seconds: int) -> list[dict[str, Any]]:
    recent_sessions: list[dict[str, Any]] = []
    for session in sessions:
        activity = session_last_activity(session)
        if activity is None:
            continue
        if activity >= now_ts - lookback_seconds:
            recent_sessions.append(session)
    return recent_sessions



def _iter_signal_events(session: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    messages = session.get('messages') or []
    for index, message in enumerate(messages):
        for tool_call in message.get('tool_calls') or []:
            function = tool_call.get('function') or {}
            tool_name = function.get('name')
            if tool_name not in _SIGNAL_TOOLS:
                continue
            args = _safe_json_loads(function.get('arguments'))
            events.append(
                {
                    'session_id': session.get('id'),
                    'title': session.get('title') or '—',
                    'message_index': index,
                    'timestamp': message.get('timestamp'),
                    'tool_name': tool_name,
                    'arguments': args,
                }
            )
    return events



def _message_excerpt(message: dict[str, Any]) -> dict[str, Any]:
    excerpt = {
        'role': message.get('role'),
        'content': (message.get('content') or '')[:500],
        'timestamp': message.get('timestamp'),
    }
    if message.get('tool_name'):
        excerpt['tool_name'] = message.get('tool_name')
    if message.get('tool_calls'):
        excerpt['tool_calls'] = [
            {
                'name': (tool_call.get('function') or {}).get('name'),
                'arguments': _safe_json_loads((tool_call.get('function') or {}).get('arguments')),
            }
            for tool_call in message.get('tool_calls') or []
        ]
    return excerpt



def build_dream_report(
    sessions: list[dict[str, Any]],
    *,
    now_ts: float,
    lookback_seconds: int,
    max_idle_seconds: int,
    state_dir: str | Path | None = None,
    overlay: dict[str, Any] | None = None,
) -> dict[str, Any]:
    last_session: dict[str, Any] | None = None
    last_activity = None
    recent_sessions = filter_recent_sessions(sessions, now_ts=now_ts, lookback_seconds=lookback_seconds)

    for session in sessions:
        activity = session_last_activity(session)
        if activity is None:
            continue
        if last_activity is None or activity > last_activity:
            last_activity = activity
            last_session = session

    idle_seconds = None if last_activity is None else int(max(0, now_ts - last_activity))
    status = 'ready'
    if last_activity is None:
        status = 'skipped'
    elif idle_seconds is not None and idle_seconds > max_idle_seconds:
        status = 'skipped'

    skill_counts: Counter[str] = Counter()
    memory_actions: Counter[str] = Counter()
    counts = Counter()
    signal_sessions: Counter[str] = Counter()
    for session in recent_sessions:
        signal_count = 0
        for event in _iter_signal_events(session):
            signal_count += 1
            counts[event['tool_name']] += 1
            if event['tool_name'] in {'skill_view', 'skill_manage'}:
                skill_name = event['arguments'].get('name')
                if isinstance(skill_name, str) and skill_name:
                    skill_counts[skill_name] += 1
            if event['tool_name'] == 'memory':
                action = event['arguments'].get('action')
                if isinstance(action, str) and action:
                    memory_actions[action] += 1
        if signal_count:
            signal_sessions[session.get('id') or 'unknown'] = signal_count

    paths = {}
    if state_dir is not None:
        base = Path(state_dir)
        paths = {
            'state_dir': str(base),
            'latest_summary': str(base / 'latest-summary.json'),
            'windows': str(base / 'windows.json'),
            'analysis_candidates': str(base / 'analysis-candidates.json'),
            'retrieval_index': str(base / 'retrieval-index.json'),
            'overlay_report': str(base / 'overlay-report.json'),
            'runs_log': str(base / 'runs.jsonl'),
        }

    return {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'status': status,
        'recent_activity': {
            'idle_seconds': idle_seconds,
            'last_session_id': last_session.get('id') if last_session else None,
            'last_title': last_session.get('title') if last_session else None,
            'recent_session_count': len(recent_sessions),
            'signal_session_count': len(signal_sessions),
        },
        'usage': {
            'skill_view_calls': counts['skill_view'],
            'skill_manage_calls': counts['skill_manage'],
            'memory_calls': counts['memory'],
            'session_search_calls': counts['session_search'],
            'memory_actions': dict(memory_actions),
            'top_skills': [
                {'name': name, 'count': count}
                for name, count in sorted(skill_counts.items(), key=lambda item: (-item[1], item[0]))
            ],
            'signal_sessions': [
                {'session_id': session_id, 'count': count}
                for session_id, count in sorted(signal_sessions.items(), key=lambda item: (-item[1], item[0]))
            ],
        },
        'paths': paths,
        'overlay': overlay or {},
    }



def extract_reflection_windows(
    sessions: list[dict[str, Any]],
    *,
    before: int = 2,
    after: int = 6,
) -> list[dict[str, Any]]:
    windows: list[dict[str, Any]] = []
    for session in sessions:
        messages = session.get('messages') or []
        signal_events = _iter_signal_events(session)
        signal_count = len(signal_events)
        for ordinal, event in enumerate(signal_events, start=1):
            start = max(0, event['message_index'] - before)
            end = min(len(messages), event['message_index'] + after + 1)
            windows.append(
                {
                    'window_id': f"{session.get('id') or 'session'}:{event['message_index']}:{event['tool_name']}",
                    'session_id': session.get('id'),
                    'title': session.get('title') or '—',
                    'tool_name': event['tool_name'],
                    'arguments': event['arguments'],
                    'message_index': event['message_index'],
                    'signal_ordinal': ordinal,
                    'signal_count_in_session': signal_count,
                    'messages': [_message_excerpt(message) for message in messages[start:end]],
                }
            )
    return windows



def _delta_counts(current: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, int]:
    current_usage = current.get('usage') or {}
    previous_usage = (previous or {}).get('usage') or {}
    keys = ('skill_view_calls', 'skill_manage_calls', 'memory_calls', 'session_search_calls')
    return {
        key: int(current_usage.get(key, 0)) - int(previous_usage.get(key, 0))
        for key in keys
    }



def _top_skill_counts(report: dict[str, Any]) -> dict[str, int]:
    usage = report.get('usage') or {}
    return {item['name']: int(item['count']) for item in usage.get('top_skills') or [] if item.get('name')}



def _estimate_window_tokens(messages: list[dict[str, Any]]) -> int:
    char_count = 0
    for message in messages:
        char_count += len(message.get('content') or '')
        for tool_call in message.get('tool_calls') or []:
            char_count += len(tool_call.get('name') or '')
            char_count += len(json.dumps(tool_call.get('arguments') or {}, sort_keys=True))
    return max(1, char_count // 4)



def _score_window(window: dict[str, Any], *, top_skill_counts: dict[str, int], session_signal_counts: dict[str, int]) -> tuple[int, list[str]]:
    tool_name = window.get('tool_name') or ''
    arguments = window.get('arguments') or {}
    score = _WINDOW_BASE_SCORES.get(tool_name, 1)
    reasons = [f'tool:{tool_name}']

    if tool_name in {'skill_view', 'skill_manage'}:
        skill_name = arguments.get('name')
        if isinstance(skill_name, str) and skill_name:
            count = top_skill_counts.get(skill_name, 0)
            if count:
                bonus = min(3, count)
                score += bonus
                reasons.append(f'skill:{skill_name}')
                reasons.append(f'skill-frequency:{count}')
        if tool_name == 'skill_manage':
            action = arguments.get('action')
            if action:
                reasons.append(f'skill-action:{action}')
            score += 2

    if tool_name == 'memory':
        action = arguments.get('action')
        if action:
            reasons.append(f'memory-action:{action}')
        if action in {'replace', 'remove'}:
            score += 3
        elif action == 'add':
            score += 1

    if tool_name == 'session_search':
        score += 1
        query = arguments.get('query')
        if isinstance(query, str) and query:
            reasons.append('cross-session-recall')

    session_signal_count = session_signal_counts.get(window.get('session_id') or '', 0)
    if session_signal_count >= 3:
        score += 2
        reasons.append(f'dense-session:{session_signal_count}')
    elif session_signal_count == 2:
        score += 1
        reasons.append('paired-signal')

    messages = window.get('messages') or []
    if len(messages) >= 6:
        score += 1
        reasons.append('longer-context')

    return score, reasons



def build_analysis_candidates(
    report: dict[str, Any],
    windows: list[dict[str, Any]],
    *,
    previous_report: dict[str, Any] | None = None,
    max_window_candidates: int = 8,
    max_session_candidates: int = 4,
) -> dict[str, Any]:
    top_skill_counts = _top_skill_counts(report)
    session_signal_counts = {
        item['session_id']: int(item['count'])
        for item in (report.get('usage') or {}).get('signal_sessions') or []
        if item.get('session_id')
    }

    ranked_windows: list[dict[str, Any]] = []
    session_rollups: defaultdict[str, dict[str, Any]] = defaultdict(lambda: {'score': 0, 'windows': [], 'title': '—', 'estimated_tokens': 0})
    for window in windows:
        score, reasons = _score_window(window, top_skill_counts=top_skill_counts, session_signal_counts=session_signal_counts)
        estimated_tokens = _estimate_window_tokens(window.get('messages') or [])
        candidate = {
            'window_id': window.get('window_id'),
            'session_id': window.get('session_id'),
            'title': window.get('title') or '—',
            'tool_name': window.get('tool_name'),
            'arguments': window.get('arguments') or {},
            'score': score,
            'reasons': reasons,
            'estimated_tokens': estimated_tokens,
            'message_count': len(window.get('messages') or []),
            'suggested_scope': 'window',
        }
        if session_signal_counts.get(window.get('session_id') or '', 0) >= 3:
            candidate['suggested_scope'] = 'session'
        ranked_windows.append(candidate)

        session_id = window.get('session_id') or 'unknown'
        rollup = session_rollups[session_id]
        rollup['score'] += score
        rollup['windows'].append(window.get('window_id'))
        rollup['title'] = window.get('title') or '—'
        rollup['estimated_tokens'] += estimated_tokens

    ranked_windows.sort(key=lambda item: (-item['score'], item['estimated_tokens'], item['window_id'] or ''))
    top_windows = ranked_windows[:max_window_candidates]

    ranked_sessions = [
        {
            'session_id': session_id,
            'title': payload['title'],
            'score': payload['score'],
            'window_ids': payload['windows'],
            'estimated_tokens': payload['estimated_tokens'],
            'suggested_scope': 'session',
        }
        for session_id, payload in session_rollups.items()
    ]
    ranked_sessions.sort(key=lambda item: (-item['score'], item['estimated_tokens'], item['session_id']))

    memory_actions = (report.get('usage') or {}).get('memory_actions') or {}
    frequent_skills = [item for item in (report.get('usage') or {}).get('top_skills') or [] if int(item.get('count', 0)) >= 2]
    memory_churn = {key: int(value) for key, value in memory_actions.items() if key in {'replace', 'remove'} and int(value) > 0}
    deltas = _delta_counts(report, previous_report)

    focus = []
    if deltas.get('skill_manage_calls', 0) > 0:
        focus.append('review recently patched skills first')
    if memory_churn:
        focus.append('review memory churn before adding more memory')
    if frequent_skills:
        focus.append('inspect high-frequency skills for overuse or missing coverage')
    if deltas.get('session_search_calls', 0) > 0:
        focus.append('compare recent recall-heavy sessions across boundaries')
    if not focus:
        focus.append('no strong new signal; keep AI review small or skip')

    return {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'report_generated_at': report.get('generated_at'),
        'status': report.get('status'),
        'baseline': {
            'previous_generated_at': (previous_report or {}).get('generated_at'),
            'previous_status': (previous_report or {}).get('status'),
        },
        'deltas': deltas,
        'summary': {
            'window_count': len(windows),
            'candidate_window_count': len(top_windows),
            'candidate_session_count': min(len(ranked_sessions), max_session_candidates),
            'frequent_skills': frequent_skills,
            'memory_churn': memory_churn,
            'focus': focus,
        },
        'window_candidates': top_windows,
        'session_candidates': ranked_sessions[:max_session_candidates],
    }



def _source_entry(*, source_id: str, kind: str, label: str, path: str | None = None, tags: tuple[str, ...] = (), metadata: dict[str, Any] | None = None, estimated_tokens: int = 0) -> dict[str, Any]:
    payload = {
        'source_id': source_id,
        'kind': kind,
        'label': label,
        'path': path,
        'tags': list(tags),
        'estimated_tokens': estimated_tokens,
    }
    if metadata:
        payload['metadata'] = metadata
    return payload



def _mode_bundle_summary(mode: str, selected_sources: list[dict[str, Any]]) -> str:
    if not selected_sources:
        return f'{mode} mode has no eligible sources yet'
    labels = ', '.join(source['label'] for source in selected_sources[:3])
    return f'{mode} mode prefers {labels}'



def _score_source_for_mode(source: dict[str, Any], mode: str) -> tuple[int, list[str]]:
    config = _MODE_RULES[mode]
    tags = set(source.get('tags') or [])
    metadata = source.get('metadata') or {}
    score = 0
    reasons: list[str] = []

    for tag in config['preferred_tags']:
        if tag in tags:
            score += 4
            reasons.append(f'tag:{tag}')
    for tag in config['avoid_tags']:
        if tag in tags:
            score -= 3
            reasons.append(f'avoid:{tag}')

    if metadata.get('score'):
        score += min(6, int(metadata['score']))
        reasons.append(f"signal:{int(metadata['score'])}")

    if metadata.get('tool_name') == 'session_search' and mode in {'reflection', 'conversational'}:
        score += 2
        reasons.append('cross-session-recall')
    if metadata.get('tool_name') == 'skill_manage' and mode == 'reflection':
        score += 3
        reasons.append('patched-skill')
    if metadata.get('tool_name') == 'memory' and mode == 'reflection':
        score += 2
        reasons.append('memory-churn')
    if source.get('source_id') == 'reflection-windows' and mode == 'reflection':
        score += 6
        reasons.append('reflection-index')
    if source.get('source_id') == 'analysis-candidates' and mode == 'reflection':
        score += 5
        reasons.append('analysis-index')
    if kind := source.get('kind'):
        if kind == 'context_file' and mode in {'coding', 'operator', 'conversational'}:
            score += 2
            reasons.append('stable-context')
            if mode == 'coding':
                score += 4
                reasons.append('coding-context')
        elif kind == 'log_file' and mode == 'operator':
            score += 2
            reasons.append('operator-log')
        elif kind == 'window' and mode == 'reflection':
            score += 2
            reasons.append('evidence-window')

    return score, reasons



def build_retrieval_index(
    report: dict[str, Any],
    windows: list[dict[str, Any]],
    analysis: dict[str, Any],
    *,
    context_files: list[str] | None = None,
    log_files: list[str] | None = None,
) -> dict[str, Any]:
    paths = report.get('paths') or {}
    sources: list[dict[str, Any]] = []

    summary_path = paths.get('latest_summary')
    if summary_path:
        sources.append(
            _source_entry(
                source_id='dream-summary',
                kind='dream_artifact',
                label='latest dream summary',
                path=summary_path,
                tags=('summary', 'reflection', 'operator', 'conversational', 'coding'),
                estimated_tokens=180,
            )
        )

    analysis_path = paths.get('analysis_candidates')
    if analysis_path:
        sources.append(
            _source_entry(
                source_id='analysis-candidates',
                kind='dream_artifact',
                label='analysis candidates',
                path=analysis_path,
                tags=('analysis', 'reflection', 'coding', 'conversational'),
                estimated_tokens=240,
                metadata={'focus': (analysis.get('summary') or {}).get('focus') or []},
            )
        )

    windows_path = paths.get('windows')
    if windows_path:
        sources.append(
            _source_entry(
                source_id='reflection-windows',
                kind='dream_artifact',
                label='reflection windows',
                path=windows_path,
                tags=('windows', 'reflection'),
                estimated_tokens=320,
            )
        )

    overlay_path = paths.get('overlay_report')
    if overlay_path:
        sources.append(
            _source_entry(
                source_id='overlay-report',
                kind='dream_artifact',
                label='overlay report',
                path=overlay_path,
                tags=('overlay', 'operator', 'summary'),
                estimated_tokens=200,
            )
        )

    runs_log = paths.get('runs_log')
    if runs_log:
        sources.append(
            _source_entry(
                source_id='dream-runs-log',
                kind='log_file',
                label='dream runs log',
                path=runs_log,
                tags=('log', 'operator', 'reflection'),
                estimated_tokens=220,
            )
        )

    for index, path in enumerate(context_files or [], start=1):
        label = Path(path).name
        tags = ('context', 'coding', 'operator', 'conversational')
        if 'memory-hierarchy' in label or 'frame-of-mind' in label:
            tags = tags + ('reflection',)
        sources.append(
            _source_entry(
                source_id=f'context-{index}',
                kind='context_file',
                label=label,
                path=path,
                tags=tags,
                estimated_tokens=260,
            )
        )

    for index, path in enumerate(log_files or [], start=1):
        sources.append(
            _source_entry(
                source_id=f'log-{index}',
                kind='log_file',
                label=Path(path).name,
                path=path,
                tags=('log', 'operator', 'reflection'),
                estimated_tokens=220,
            )
        )

    for candidate in (analysis.get('window_candidates') or [])[:6]:
        label = f"window {candidate.get('window_id')}"
        tool_name = candidate.get('tool_name') or 'signal'
        tags = ('reflection', 'analysis', 'window')
        if tool_name == 'skill_manage':
            tags = tags + ('coding',)
        if tool_name == 'session_search':
            tags = tags + ('conversational',)
        metadata = {
            'window_id': candidate.get('window_id'),
            'session_id': candidate.get('session_id'),
            'tool_name': tool_name,
            'score': int(candidate.get('score') or 0),
            'reasons': candidate.get('reasons') or [],
        }
        sources.append(
            _source_entry(
                source_id=f"window-{candidate.get('window_id')}",
                kind='window',
                label=label,
                tags=tags,
                metadata=metadata,
                estimated_tokens=int(candidate.get('estimated_tokens') or 0),
            )
        )

    modes: dict[str, Any] = {}
    for mode in _MODE_RULES:
        scored: list[dict[str, Any]] = []
        for source in sources:
            score, reasons = _score_source_for_mode(source, mode)
            if score <= 0:
                continue
            candidate = dict(source)
            candidate['score'] = score
            candidate['reasons'] = reasons
            scored.append(candidate)
        scored.sort(key=lambda item: (-item['score'], item.get('estimated_tokens', 0), item['source_id']))
        selected = scored[: _MODE_RULES[mode]['max_sources']]
        modes[mode] = {
            'summary': _mode_bundle_summary(mode, selected),
            'bundle': selected,
            'source_ids': [item['source_id'] for item in selected],
            'estimated_tokens': sum(int(item.get('estimated_tokens') or 0) for item in selected),
        }

    return {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'report_generated_at': report.get('generated_at'),
        'analysis_generated_at': analysis.get('generated_at'),
        'status': report.get('status'),
        'source_count': len(sources),
        'sources': sources,
        'modes': modes,
    }



def render_motd(report: dict[str, Any], analysis: dict[str, Any] | None = None) -> str:
    recent = report.get('recent_activity') or {}
    usage = report.get('usage') or {}
    paths = report.get('paths') or {}
    overlay = report.get('overlay') or {}

    top_skill = 'none'
    if usage.get('top_skills'):
        skill = usage['top_skills'][0]
        top_skill = f"{skill['name']} ({skill['count']})"

    idle_seconds = recent.get('idle_seconds')
    idle_label = 'unknown'
    if isinstance(idle_seconds, int):
        idle_label = f'{max(0, idle_seconds // 60)}m ago'

    overlay_label = 'overlay: unavailable'
    if overlay:
        dirty_label = 'dirty' if overlay.get('dirty') else 'clean'
        upstream = overlay.get('upstream_ref') or '?'
        patch_count = overlay.get('exported_patch_count')
        patch_label = f' patches={patch_count}' if patch_count is not None else ''
        overlay_label = (
            f"overlay: {overlay.get('label', 'repo')} {overlay.get('branch', '?')} "
            f"vs {upstream} +{overlay.get('ahead', 0)}/-{overlay.get('behind', 0)} {dirty_label}{patch_label}"
        )

    recent_label = recent.get('last_title') or recent.get('last_session_id') or 'none'
    lines = [
        'Hermes summary',
        f"- dream status: {report.get('status', 'unknown')} (last chat {idle_label})",
        f"- recent session: {recent_label} [{recent.get('last_session_id') or '-'}]",
        f"- skill activity: view={usage.get('skill_view_calls', 0)} patch={usage.get('skill_manage_calls', 0)}; top skill: {top_skill}",
        f"- memory activity: calls={usage.get('memory_calls', 0)} actions={json.dumps(usage.get('memory_actions', {}), sort_keys=True)}",
        f"- {overlay_label}",
    ]
    if analysis:
        summary = analysis.get('summary') or {}
        focus = (summary.get('focus') or ['no analysis focus'])[:2]
        lines.append(
            f"- dream queue: windows={summary.get('candidate_window_count', 0)} sessions={summary.get('candidate_session_count', 0)}"
        )
        lines.append(f"- focus: {'; '.join(focus)}")
    if paths:
        lines.extend(
            [
                f"- summary: {paths.get('latest_summary')}",
                f"- windows: {paths.get('windows')}",
                f"- analysis: {paths.get('analysis_candidates')}",
                f"- retrieval index: {paths.get('retrieval_index')}",
                f"- overlay report: {paths.get('overlay_report')}",
                f"- dream log: {paths.get('runs_log')}",
            ]
        )
    lines.append('- more: open the JSON artifacts or ask Hermes for a deeper analysis')
    return '\n'.join(lines)
