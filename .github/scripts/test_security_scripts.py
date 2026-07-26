from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


SCRIPT_ROOT = Path(__file__).resolve().parent


def _load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPT_ROOT / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


scan = _load_module("security_source_scan", "security_source_scan.py")
sanitize = _load_module("sanitize_dependency_audit", "sanitize_dependency_audit.py")


class SecuritySourceScanTests(unittest.TestCase):
    def test_multiline_browser_credentials_and_all_vite_secret_families_are_rejected(self):
        browser_storage = "local" + "Storage"
        bearer = "Author" + "ization"
        source = (
            f"{browser_storage}.setItem(\n'access_token', value)\n"
            f"headers['{bearer}'] =\n'Bearer ' + token\n"
        )
        findings = scan._scan_text("frontend/src/example.ts", source, scan.FRONTEND_RULES)
        self.assertIn("browser-token-storage", str(findings))
        self.assertIn("browser-bearer-injection", str(findings))

        indexed_db = scan._scan_text(
            "frontend/src/indexed-db.ts",
            "indexedDB.open('mata').transaction('auth').objectStore('auth')"
            ".put(access_token)",
            scan.FRONTEND_RULES,
        )
        self.assertIn("browser-indexeddb-token-storage", str(indexed_db))

        for suffix_parts in (
            ("SERVICE", "ROLE"),
            ("SESSION", "HASH"),
            ("RESIDENT", "SESSION"),
            ("DATABASE", "URL"),
            ("SYNC", "DATABASE", "URL"),
            ("PRIVATE", "KEY"),
            ("DB", "PASSWORD"),
            ("RATE", "LIMIT", "HASH"),
            ("JWT", "SECRET"),
            ("SECRET", "KEY"),
        ):
            name = "VITE_SAMPLE_" + "_".join(suffix_parts)
            findings = scan._scan_text(
                "frontend/vite.config.ts",
                name,
                scan.FRONTEND_RULES,
            )
            self.assertIn("vite-backend-secret", str(findings), name)

        backend_name = "_".join(("SUPABASE", "SERVICE", "ROLE", "KEY"))
        findings = scan._scan_text(
            "frontend/src/runtime.ts",
            f"window.config.{backend_name}",
            scan.FRONTEND_RULES,
        )
        self.assertIn("frontend-backend-secret-name", str(findings))

    def test_backend_secret_values_are_redacted_and_placeholders_are_allowed(self):
        secret_name = "_".join(("RATE", "LIMIT", "HASH", "SECRET"))
        finding = scan._scan_text(
            "backend.env",
            f"{secret_name}=sentinel-sensitive-value",
            scan.SECRET_RULES,
        )
        self.assertEqual(["backend-secret-assignment: backend.env:1"], finding)
        self.assertNotIn("sentinel-sensitive-value", str(finding))

        placeholder = scan._scan_text(
            ".env.example",
            f"{secret_name}=<replace-with-random-value>",
            scan.SECRET_RULES,
        )
        self.assertEqual([], placeholder)
        lower_case_setting = scan._scan_text(
            "backend/app/config.py",
            "database_url: str",
            scan.SECRET_RULES,
        )
        self.assertEqual([], lower_case_setting)

    def test_placeholder_matching_is_anchored_and_rejects_mixed_values(self):
        accepted = (
            "<replace-with-random-value>",
            "${RUNTIME_SECRET}",
            "{{ secrets.RUNTIME_SECRET }}",
            "postgresql+asyncpg://<user>:<password>@<host>:5432/<database>",
            "postgresql://${DB_USER}:${DB_PASSWORD}@${DB_HOST}:5432/${DB_NAME}",
            "https://<project-ref>.supabase.co",
            "postgresql+asyncpg://postgres:postgres@localhost:5432/mata_phase5b_verify_ci",
            "https://api.example.invalid",
        )
        rejected = (
            "real-<placeholder>",
            "<placeholder>-real",
            "real${RUNTIME_SECRET}",
            "${RUNTIME_SECRET}-real",
            "postgresql://admin:realpass@<host>/<database>",
        )
        for value in accepted:
            self.assertTrue(scan._is_placeholder(value), value)
        for value in rejected:
            self.assertFalse(scan._is_placeholder(value), value)

        secret_name = "_".join(("DATABASE", "URL"))
        sentinel = "sentinel-sensitive-value"
        finding = scan._scan_text(
            "config.env",
            f"{secret_name}=postgresql://admin:{sentinel}@<host>/<database>",
            scan.SECRET_RULES,
        )
        self.assertEqual(["backend-secret-assignment: config.env:1"], finding)
        self.assertNotIn(sentinel, str(finding))

    def test_supabase_client_auth_and_dependency_patterns_are_rejected(self):
        samples = (
            ("client.auth.getSession()", "supabase-session-auth"),
            (
                "fetch('https://project.supabase.co/auth/v1/token')",
                "direct-supabase-auth-api",
            ),
            (
                "import { createClient as aliased } from '@supabase/supabase-js'",
                "supabase-client-package",
            ),
            (
                '"dependencies": {"@supabase/auth-js": "1.0.0"}',
                "supabase-client-package",
            ),
        )
        for source, rule_id in samples:
            findings = scan._scan_text(
                "frontend/public/runtime.js",
                source,
                scan.FRONTEND_RULES,
            )
            self.assertIn(rule_id, str(findings), source)

    def test_frontend_inventory_includes_public_text_assets(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "frontend" / "src").mkdir(parents=True)
            (root / "frontend" / "public").mkdir(parents=True)
            public_asset = root / "frontend" / "public" / "runtime-config.js"
            public_asset.write_text("window.config = {}", encoding="utf-8")
            nginx = root / "frontend" / "nginx.conf"
            nginx.write_text("server {}", encoding="utf-8")
            with mock.patch.object(scan, "ROOT", root):
                paths = scan._frontend_source_paths()
            self.assertIn(public_asset, paths)
            self.assertIn(nginx, paths)

    def test_frontend_scan_decodes_utf16_text(self):
        backend_name = "_".join(("DATABASE", "URL"))
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_root = root / "frontend" / "src"
            source_root.mkdir(parents=True)
            source = source_root / "runtime.ts"
            source.write_text(
                f"window.config.{backend_name}",
                encoding="utf-16",
            )
            with mock.patch.object(scan, "ROOT", root):
                findings = scan.scan_frontend()
        self.assertIn("frontend-backend-secret-name", str(findings))

    def test_worktree_scan_covers_tracked_added_lines_without_echoing_values(self):
        secret_name = "_".join(("MATA", "SESSION", "HASH", "KEY"))
        sentinel = "sentinel-sensitive-value"
        patch = (
            "diff --git a/config.env b/config.env\n"
            "+++ b/config.env\n"
            "@@ -0,0 +1 @@\n"
            f"+{secret_name}={sentinel}\n"
        )
        with (
            mock.patch.object(scan, "_git_worktree_patch", return_value=patch),
            mock.patch.object(scan, "_git_untracked_paths", return_value=[]),
        ):
            findings = scan.scan_worktree()
        self.assertEqual(["backend-secret-assignment: config.env:1"], findings)
        self.assertNotIn(sentinel, str(findings))

    def test_worktree_scan_covers_untracked_text_without_echoing_values(self):
        secret_name = "_".join(("RATE", "LIMIT", "HASH", "SECRET"))
        sentinel = "sentinel-sensitive-value"
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            untracked = root / "new.env"
            untracked.write_text(f"{secret_name}={sentinel}\n", encoding="utf-8")
            with (
                mock.patch.object(scan, "ROOT", root),
                mock.patch.object(scan, "_git_worktree_patch", return_value=""),
                mock.patch.object(
                    scan,
                    "_git_untracked_paths",
                    return_value=["new.env"],
                ),
            ):
                findings = scan.scan_worktree()
        self.assertEqual(["backend-secret-assignment: new.env:1"], findings)
        self.assertNotIn(sentinel, str(findings))

    def test_worktree_scan_covers_utf16_untracked_text_without_echoing_values(self):
        secret_name = "_".join(("MATA", "SESSION", "HASH", "KEY"))
        sentinel = "sentinel-sensitive-value"
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            untracked = root / "new.env"
            untracked.write_text(
                f"{secret_name}={sentinel}\n",
                encoding="utf-16",
            )
            with (
                mock.patch.object(scan, "ROOT", root),
                mock.patch.object(scan, "_git_worktree_patch", return_value=""),
                mock.patch.object(
                    scan,
                    "_git_untracked_paths",
                    return_value=["new.env"],
                ),
            ):
                findings = scan.scan_worktree()
        self.assertEqual(["backend-secret-assignment: new.env:1"], findings)
        self.assertNotIn(sentinel, str(findings))

    def test_worktree_scan_fails_closed_when_git_state_is_unavailable(self):
        with (
            mock.patch.object(scan, "_git_worktree_patch", return_value=None),
            mock.patch.object(scan, "_git_untracked_paths", return_value=[]),
        ):
            self.assertEqual(
                ["secret-worktree-scan-unavailable"],
                scan.scan_worktree(),
            )

    def test_unresolvable_empty_diff_base_fails_closed(self):
        with mock.patch.object(scan, "_resolve_diff_base", return_value=None):
            self.assertEqual(
                ["secret-diff-scan-unavailable"],
                scan.scan_added_diff("0" * 40),
            )

    def test_binary_text_diff_fails_closed_without_blocking_binary_assets(self):
        text_patch = (
            "diff --git a/frontend/src/runtime.ts b/frontend/src/runtime.ts\n"
            "Binary files a/frontend/src/runtime.ts and b/frontend/src/runtime.ts differ\n"
        )
        asset_patch = (
            "diff --git a/frontend/public/logo.png b/frontend/public/logo.png\n"
            "Binary files a/frontend/public/logo.png and b/frontend/public/logo.png differ\n"
        )
        self.assertEqual(
            ["secret-binary-text-unscannable: frontend/src/runtime.ts"],
            scan._scan_added_patch(text_patch),
        )
        self.assertEqual([], scan._scan_added_patch(asset_patch))


class DependencySanitizerTests(unittest.TestCase):
    def test_reports_contain_only_approved_dependency_and_advisory_metadata(self):
        pip_payload = {
            "dependencies": [
                {
                    "name": "runtime-package",
                    "version": "1.2.3",
                    "vulns": [
                        {
                            "id": "PYSEC-TEST",
                            "description": "sensitive description",
                            "fix_versions": ["9.9.9"],
                        }
                    ],
                }
            ]
        }
        npm_payload = {
            "vulnerabilities": {
                "browser-package": {
                    "range": "<1.0.0",
                    "severity": "high",
                    "via": [
                        {
                            "source": 12345,
                            "url": "https://security.invalid/private",
                            "title": "private advisory title",
                        }
                    ],
                    "fixAvailable": {
                        "name": "browser-package",
                        "version": "1.0.0",
                    },
                }
            }
        }
        npm_lock_payload = {
            "packages": {
                "": {"dependencies": {"browser-package": "0.9.0"}},
                "node_modules/browser-package": {"version": "0.9.0"},
            }
        }
        self.assertEqual(
            [
                {
                    "package": "runtime-package",
                    "declared_version": "1.2.3",
                    "advisories": [
                        {
                            "advisory_ids": ["PYSEC-TEST"],
                            "severity": None,
                            "fixed_versions": ["9.9.9"],
                        }
                    ],
                }
            ],
            sanitize._pip_findings(pip_payload),
        )
        self.assertEqual(
            [
                {
                    "package": "browser-package",
                    "version_range": "<1.0.0",
                    "advisory_ids": ["12345"],
                    "severity": "high",
                    "dependency_type": "runtime",
                    "recommended_fixed_version": "1.0.0",
                }
            ],
            sanitize._npm_findings(npm_payload, npm_lock_payload),
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "report.json"
            path.write_text(
                json.dumps(
                    {
                        "pip": sanitize._pip_findings(pip_payload),
                        "npm": sanitize._npm_findings(
                            npm_payload,
                            npm_lock_payload,
                        ),
                    }
                ),
                encoding="utf-8",
            )
            report = path.read_text(encoding="utf-8")
        for forbidden in ("sensitive description", "security.invalid", "private advisory title"):
            self.assertNotIn(forbidden, report)

    def test_missing_and_malformed_audit_inputs_are_not_reported_as_clean(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            missing_payload, missing_status = sanitize._load(root / "missing.json")
            malformed_path = root / "malformed.json"
            malformed_path.write_text("{not-json", encoding="utf-8")
            malformed_payload, malformed_status = sanitize._load(malformed_path)
            clean_path = root / "clean.json"
            clean_path.write_text("{}", encoding="utf-8")
            clean_payload, clean_status = sanitize._load(clean_path)

        self.assertIsNone(missing_payload)
        self.assertEqual("missing", missing_status)
        self.assertIsNone(malformed_payload)
        self.assertEqual("invalid", malformed_status)
        self.assertEqual({}, clean_payload)
        self.assertEqual("parsed", clean_status)
        self.assertEqual(
            "invalid_schema",
            sanitize._schema_status(clean_payload, clean_status, scanner="pip"),
        )
        self.assertEqual(
            "invalid_schema",
            sanitize._schema_status(clean_payload, clean_status, scanner="npm"),
        )
        self.assertEqual(
            "parsed",
            sanitize._schema_status(
                {
                    "dependencies": [
                        {"name": "runtime", "version": "1.0.0", "vulns": []}
                    ]
                },
                "parsed",
                scanner="pip",
            ),
        )
        self.assertEqual(
            "parsed",
            sanitize._schema_status(
                {"vulnerabilities": {}},
                "parsed",
                scanner="npm",
            ),
        )

    def test_nested_audit_schema_is_validated(self):
        self.assertEqual(
            "invalid_schema",
            sanitize._schema_status(
                {"dependencies": [{"name": "runtime", "vulns": "invalid"}]},
                "parsed",
                scanner="pip",
            ),
        )
        self.assertEqual(
            "invalid_schema",
            sanitize._schema_status(
                {"vulnerabilities": {"runtime": "invalid"}},
                "parsed",
                scanner="npm",
            ),
        )

    def test_invalid_audit_schema_fails_closed_after_writing_redacted_status(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            malformed_schema = root / "schema.json"
            malformed_schema.write_text("{}", encoding="utf-8")
            output = root / "sanitized.json"
            with mock.patch.object(
                sys,
                "argv",
                [
                    "sanitize_dependency_audit.py",
                    "--pip",
                    str(malformed_schema),
                    "--output",
                    str(output),
                ],
            ):
                self.assertEqual(1, sanitize.main())
            report = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual("invalid_schema", report["scan_status"]["pip"])
        self.assertEqual("not_requested", report["scan_status"]["npm"])


if __name__ == "__main__":
    unittest.main()
