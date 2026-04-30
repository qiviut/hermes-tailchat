from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import textwrap
from typing import Any, Iterator, Sequence

FORBIDDEN_FLAGS = {
    "--verbose",
    "-v",
    "--bearer-token",
    "--consumer-key",
    "--consumer-secret",
    "--access-token",
    "--token-secret",
    "--client-id",
    "--client-secret",
}


class XurlCommandError(RuntimeError):
    pass


@dataclass(frozen=True)
class XurlClient:
    xurl_path: str = "xurl"
    home: Path | None = None
    app_name: str | None = None
    auth: str = "app"

    def build_command(self, args: Sequence[str]) -> list[str]:
        forbidden = [arg for arg in args if arg in FORBIDDEN_FLAGS]
        if forbidden:
            raise ValueError(f"forbidden xurl flags in agent session: {', '.join(forbidden)}")
        cmd = [self.xurl_path]
        if self.app_name:
            cmd.extend(["--app", self.app_name])
        if self.auth:
            cmd.extend(["--auth", self.auth])
        cmd.extend(args)
        return cmd

    def get_json(self, endpoint: str) -> dict[str, Any]:
        if not endpoint.startswith("/2/"):
            raise ValueError("xurl endpoint must be an X API v2 path")
        env = os.environ.copy()
        if self.home is not None:
            env["HOME"] = str(self.home)
        cp = subprocess.run(
            self.build_command([endpoint]),
            check=False,
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
        if cp.returncode != 0:
            parsed = _try_json(cp.stdout)
            if isinstance(parsed, dict) and "errors" in parsed:
                raise XurlCommandError(_summarize_errors(parsed))
            raise XurlCommandError(_redacted_error("xurl command failed", cp.stderr or cp.stdout))
        return parse_xurl_json(cp.stdout, cp.stderr)


def parse_xurl_json(stdout: str, stderr: str) -> dict[str, Any]:
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError:
        raise XurlCommandError(_redacted_error("xurl returned non-json output", stderr or stdout)) from None
    if not isinstance(parsed, dict):
        raise XurlCommandError("xurl returned unexpected non-object JSON")
    return parsed


@contextmanager
def build_temp_xurl_home(*, app_name: str, client_id: str, client_secret: str, bearer_token: str) -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="xurl-home-") as tmp:
        home = Path(tmp)
        os.chmod(home, 0o700)
        config = home / ".xurl"
        config.write_text(
            textwrap.dedent(
                f"""\
                apps:
                  {app_name}:
                    client_id: "{client_id}"
                    client_secret: "{client_secret}"
                    oauth2_tokens: {{}}
                    bearer_token:
                      type: bearer
                      bearer: "{bearer_token}"
                default_app: {app_name}
                """
            )
        )
        os.chmod(config, 0o600)
        yield home


def _try_json(raw: str) -> Any:
    try:
        return json.loads(raw)
    except Exception:
        return None


def _summarize_errors(payload: dict[str, Any]) -> str:
    summaries: list[str] = []
    for item in payload.get("errors", [])[:3]:
        if isinstance(item, dict):
            title = str(item.get("title") or item.get("message") or "X API error")[:120]
            detail = str(item.get("detail") or item.get("code") or "")[:200]
            summaries.append(f"{title}: {detail}" if detail else title)
    return "; ".join(summaries) or "X API error"


def _redacted_error(prefix: str, raw: str) -> str:
    if not raw:
        return prefix
    redacted = re.sub(r"[A-Za-z0-9_%=:+/.-]{24,}", "[REDACTED]", raw)
    # Do not include arbitrary non-JSON stdout from X/tooling; it may contain
    # hostile text or secrets. Only report that bounded output existed.
    return f"{prefix}: {len(redacted)} bytes redacted"
