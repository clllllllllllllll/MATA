#!/usr/bin/env python3
"""Fail CI on browser-auth regressions or likely secrets without echoing values."""

from __future__ import annotations

import argparse
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Rule:
    rule_id: str
    pattern: re.Pattern[str]


FRONTEND_RULES = (
    Rule(
        "browser-token-storage",
        re.compile(
            r"(?:sessionStorage|localStorage)[\s\S]{0,100}"
            r"(?:access[_-]?token|refresh[_-]?token|resident[_-]?token|auth[_-]?token)",
            re.IGNORECASE,
        ),
    ),
    Rule(
        "browser-indexeddb-token-storage",
        re.compile(
            r"(?:(?:indexedDB|IDBDatabase|IDBObjectStore)[\s\S]{0,160}"
            r"(?:access[_-]?token|refresh[_-]?token|resident[_-]?token|auth[_-]?token)"
            r"|(?:access[_-]?token|refresh[_-]?token|resident[_-]?token|auth[_-]?token)"
            r"[\s\S]{0,160}(?:indexedDB|IDBDatabase|IDBObjectStore))",
            re.IGNORECASE,
        ),
    ),
    Rule(
        "browser-bearer-injection",
        re.compile(r"Authorization[\s\S]{0,80}Bearer", re.IGNORECASE),
    ),
    Rule(
        "supabase-session-auth",
        re.compile(
            r"\.auth\s*\.\s*(?:getSession|setSession|refreshSession|"
            r"onAuthStateChange|signInWithPassword|signInWithOtp|signOut)\s*\("
            r"|\.getSession\s*\(",
            re.IGNORECASE,
        ),
    ),
    Rule(
        "supabase-client-package",
        re.compile(r"@supabase/(?:supabase-js|auth-js|ssr)", re.IGNORECASE),
    ),
    Rule(
        "direct-supabase-auth-api",
        re.compile(
            r"(?:https?://[^/\s\"']*supabase\.co)?/auth/v1/"
            r"(?:token|user|logout|signup|verify|recover|otp|admin)\b",
            re.IGNORECASE,
        ),
    ),
    Rule(
        "direct-supabase-data-api",
        re.compile(
            r"\b(?:supabase|client)\.(?:from|rpc)\s*\(|/(?:rest|graphql)/v1/",
            re.IGNORECASE,
        ),
    ),
    Rule(
        "supabase-client-construction",
        re.compile(r"\bsupabase\.createClient\s*\(|\bcreateBrowserClient\s*\(", re.IGNORECASE),
    ),
    Rule(
        "vite-backend-secret",
        re.compile(
            r"VITE_[A-Z0-9_]*(?:SERVICE_ROLE|SESSION_HASH|RESIDENT_SESSION|"
            r"DATABASE_URL|SYNC_DATABASE_URL|PRIVATE_KEY|DB_PASSWORD|"
            r"RATE_LIMIT_HASH|JWT_SECRET|SECRET_KEY)"
        ),
    ),
    Rule(
        "frontend-backend-secret-name",
        re.compile(
            r"\b(?:SUPABASE_SERVICE_ROLE_KEY|MATA_SESSION_HASH_KEY|"
            r"MATA_RESIDENT_SESSION_SECRET|RATE_LIMIT_HASH_SECRET|JWT_SECRET|"
            r"SECRET_KEY|DATABASE_URL|SYNC_DATABASE_URL|PRIVATE_KEY|DB_PASSWORD)\b"
        ),
    ),
)

SECRET_RULES = (
    Rule("private-key-material", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    Rule("github-token", re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b")),
    Rule("aws-access-key", re.compile(r"\bAKIA[A-Z0-9]{16}\b")),
    Rule(
        "backend-secret-assignment",
        re.compile(
            r"['\"]?(?:SUPABASE_SERVICE_ROLE_KEY|MATA_SESSION_HASH_KEY|"
            r"MATA_RESIDENT_SESSION_SECRET|RATE_LIMIT_HASH_SECRET|JWT_SECRET|"
            r"SECRET_KEY|DATABASE_URL|SYNC_DATABASE_URL|PRIVATE_KEY|DB_PASSWORD)"
            r"['\"]?\s*[:=]\s*['\"]?([^,'\"\r\n]+)",
        ),
    ),
)

TEXT_SUFFIXES = {
    ".css",
    ".cjs",
    ".conf",
    ".env",
    ".html",
    ".js",
    ".json",
    ".jsx",
    ".mjs",
    ".md",
    ".svg",
    ".txt",
    ".ts",
    ".tsx",
    ".webmanifest",
    ".xml",
    ".yaml",
    ".yml",
}

MAX_WORKTREE_TEXT_BYTES = 5 * 1024 * 1024
_PLACEHOLDER_TOKEN = (
    r"(?:<[^<>\r\n]+>|\$\{[A-Za-z_][A-Za-z0-9_]*\}|"
    r"\{\{\s*(?:secrets\.)?[A-Za-z_][A-Za-z0-9_.]*\s*\}\})"
)
_PLACEHOLDER_TOKEN_RE = re.compile(rf"^{_PLACEHOLDER_TOKEN}$", re.IGNORECASE)
_PLACEHOLDER_DATABASE_URL_RE = re.compile(
    rf"^postgresql(?:\+(?:asyncpg|psycopg|psycopg2))?://"
    rf"{_PLACEHOLDER_TOKEN}(?::{_PLACEHOLDER_TOKEN})?@"
    rf"{_PLACEHOLDER_TOKEN}(?::(?:\d+|{_PLACEHOLDER_TOKEN}))?/"
    rf"{_PLACEHOLDER_TOKEN}$",
    re.IGNORECASE,
)
_PLACEHOLDER_HTTP_URL_RE = re.compile(
    rf"^https?://{_PLACEHOLDER_TOKEN}(?:\.[A-Za-z0-9.-]+)?"
    rf"(?::(?:\d+|{_PLACEHOLDER_TOKEN}))?(?:/{_PLACEHOLDER_TOKEN})?/?$",
    re.IGNORECASE,
)


def _is_text_candidate(path: str | Path) -> bool:
    candidate = Path(path)
    return (
        candidate.suffix.lower() in TEXT_SUFFIXES
        or candidate.name.casefold().startswith(".env")
        or candidate.name in {"Dockerfile", "nginx.conf"}
    )


def _decode_text(content: bytes) -> str | None:
    if content.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return content.decode("utf-16")
        except UnicodeError:
            return None
    if b"\0" in content:
        even_nulls = content[0::2].count(0)
        odd_nulls = content[1::2].count(0)
        if max(even_nulls, odd_nulls) < max(1, len(content) // 8):
            return None
        encoding = "utf-16-le" if odd_nulls >= even_nulls else "utf-16-be"
        try:
            decoded = content.decode(encoding)
        except UnicodeError:
            return None
        return None if "\0" in decoded else decoded
    try:
        return content.decode("utf-8-sig")
    except UnicodeError:
        return None


def _is_placeholder(value: str) -> bool:
    normalised = value.strip().strip("'\"").strip()
    lowered = normalised.casefold()
    if not normalised:
        return True
    if lowered in {
        "...",
        "…",
        "changeme",
        "change-me",
        "replace-me",
        "example",
        "redacted",
        "placeholder",
    }:
        return True
    if (
        _PLACEHOLDER_TOKEN_RE.fullmatch(normalised)
        or _PLACEHOLDER_DATABASE_URL_RE.fullmatch(normalised)
        or _PLACEHOLDER_HTTP_URL_RE.fullmatch(normalised)
    ):
        return True

    try:
        parsed = urlsplit(normalised)
        hostname = (parsed.hostname or "").casefold()
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https", "postgresql", "postgresql+asyncpg",
                             "postgresql+psycopg", "postgresql+psycopg2"}:
        return False
    if hostname in {"localhost", "127.0.0.1", "::1", "db"}:
        if parsed.scheme.startswith("postgresql"):
            return (
                parsed.username in {None, "postgres"}
                and parsed.password in {None, "postgres"}
            )
        return parsed.username is None and parsed.password is None
    if hostname == "example.com" or hostname.endswith(".example.com") or hostname.endswith(
        ".invalid"
    ):
        return parsed.password is None
    return False


def _scan_text(
    path: str,
    text: str,
    rules: tuple[Rule, ...],
    *,
    starting_line: int = 1,
) -> list[str]:
    findings: list[str] = []
    for rule in rules:
        for match in rule.pattern.finditer(text):
            if (
                rule.rule_id == "backend-secret-assignment"
                and _is_placeholder(match.group(1))
            ):
                continue
            line_number = starting_line + text.count("\n", 0, match.start())
            findings.append(f"{rule.rule_id}: {path}:{line_number}")
    return findings


def _frontend_source_paths() -> list[Path]:
    frontend_root = ROOT / "frontend"
    paths: list[Path] = []
    for source_root in (frontend_root / "src", frontend_root / "public"):
        if source_root.is_dir():
            paths.extend(
                path
                for path in source_root.rglob("*")
                if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES
            )
    for name in (
        "Dockerfile",
        "index.html",
        "nginx.conf",
        "package.json",
        "package-lock.json",
        "vercel.json",
        "vite.config.js",
        "vite.config.mjs",
        "vite.config.ts",
    ):
        candidate = frontend_root / name
        if candidate.is_file():
            paths.append(candidate)
    paths.extend(path for path in frontend_root.glob(".env*") if path.is_file())
    return sorted(set(paths))


def scan_frontend() -> list[str]:
    findings: list[str] = []
    for path in _frontend_source_paths():
        if ".test." in path.name or ".spec." in path.name:
            continue
        relative = path.relative_to(ROOT).as_posix()
        try:
            content = path.read_bytes()
        except OSError:
            findings.append(f"frontend-file-unreadable: {relative}")
            continue
        text = _decode_text(content)
        if text is None:
            findings.append(f"frontend-file-unreadable: {relative}")
            continue
        findings.extend(
            _scan_text(
                relative,
                text,
                FRONTEND_RULES,
            )
        )
    return findings


def _git_stdout(*args: str) -> str | None:
    completed = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        return None
    value = completed.stdout.strip()
    return value or None


def _resolve_diff_base(base: str | None) -> str | None:
    if base and set(base) != {"0"}:
        return base

    candidates: list[str] = []
    origin_head = _git_stdout("symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if origin_head:
        candidates.append(origin_head)
    candidates.extend(("origin/main", "origin/master"))
    for candidate in dict.fromkeys(candidates):
        merge_base = _git_stdout("merge-base", "HEAD", candidate)
        if merge_base:
            return merge_base
    return None


def scan_added_diff(base: str | None) -> list[str]:
    resolved_base = _resolve_diff_base(base)
    if resolved_base is None:
        print("secret-diff-scan: comparison base unavailable", file=sys.stderr)
        return ["secret-diff-scan-unavailable"]
    completed = subprocess.run(
        ["git", "diff", "--unified=0", f"{resolved_base}...HEAD"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        print("secret-diff-scan: comparison base unavailable", file=sys.stderr)
        return ["secret-diff-scan-unavailable"]
    return _scan_added_patch(completed.stdout)


def _scan_added_patch(patch_text: str) -> list[str]:
    findings: list[str] = []
    current_path = "unknown"
    added_line = 0
    segment_start = 0
    segment_lines: list[str] = []

    def flush_segment() -> None:
        nonlocal segment_lines
        if segment_lines:
            findings.extend(
                _scan_text(
                    current_path,
                    "\n".join(segment_lines),
                    SECRET_RULES,
                    starting_line=segment_start,
                )
            )
            segment_lines = []

    for line in patch_text.splitlines():
        if line.startswith("diff --git "):
            flush_segment()
            try:
                parts = shlex.split(line)
            except ValueError:
                parts = []
            if len(parts) >= 4 and parts[3].startswith("b/"):
                current_path = parts[3][2:]
            continue
        if line.startswith("+++ b/"):
            flush_segment()
            current_path = line[6:]
            continue
        if line.startswith("Binary files "):
            flush_segment()
            if _is_text_candidate(current_path):
                findings.append(f"secret-binary-text-unscannable: {current_path}")
            continue
        if line.startswith("@@"):
            flush_segment()
            match = re.search(r"\+(\d+)", line)
            added_line = int(match.group(1)) if match else 0
            continue
        if not line.startswith("+") or line.startswith("+++"):
            flush_segment()
            continue
        if not segment_lines:
            segment_start = added_line
        content = line[1:]
        segment_lines.append(content)
        added_line += 1
    flush_segment()
    return findings


def _git_worktree_patch() -> str | None:
    completed = subprocess.run(
        ["git", "diff", "--unified=0", "--no-ext-diff", "HEAD", "--"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return completed.stdout if completed.returncode == 0 else None


def _git_untracked_paths() -> list[str] | None:
    completed = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        return None
    return [
        path.decode("utf-8", errors="replace")
        for path in completed.stdout.split(b"\0")
        if path
    ]


def _scan_untracked_file(relative_path: str) -> list[str]:
    root = ROOT.resolve()
    candidate = ROOT / relative_path
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError):
        return [f"worktree-untracked-file-unreadable: {relative_path}"]
    if candidate.is_symlink() or not resolved.is_file():
        return [f"worktree-untracked-file-unreadable: {relative_path}"]
    try:
        if resolved.stat().st_size > MAX_WORKTREE_TEXT_BYTES:
            return [f"worktree-untracked-file-too-large: {relative_path}"]
        content = resolved.read_bytes()
    except OSError:
        return [f"worktree-untracked-file-unreadable: {relative_path}"]
    if b"\0" in content and not _is_text_candidate(resolved):
        return []
    text = _decode_text(content)
    if text is None:
        return [f"worktree-untracked-file-unreadable: {relative_path}"]
    return _scan_text(
        relative_path.replace("\\", "/"),
        text,
        SECRET_RULES,
    )


def scan_worktree() -> list[str]:
    patch = _git_worktree_patch()
    untracked_paths = _git_untracked_paths()
    if patch is None or untracked_paths is None:
        print("secret-worktree-scan: worktree state unavailable", file=sys.stderr)
        return ["secret-worktree-scan-unavailable"]

    findings = _scan_added_patch(patch)
    for relative_path in untracked_paths:
        findings.extend(_scan_untracked_file(relative_path))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frontend", action="store_true")
    parser.add_argument("--diff-base")
    parser.add_argument("--worktree", action="store_true")
    args = parser.parse_args()

    findings: list[str] = []
    if args.frontend:
        findings.extend(scan_frontend())
    if args.diff_base is not None:
        findings.extend(scan_added_diff(args.diff_base))
    if args.worktree:
        findings.extend(scan_worktree())

    if findings:
        print("Security source scan failed; matched values are intentionally redacted.")
        for finding in sorted(set(findings)):
            print(f"- {finding}")
        return 1
    print("Security source scan passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
