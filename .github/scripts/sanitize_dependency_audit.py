#!/usr/bin/env python3
"""Reduce dependency scanner JSON to approved dependency and advisory metadata."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load(path: Path | None) -> tuple[Any, str]:
    if path is None:
        return None, "not_requested"
    if not path.exists():
        return None, "missing"
    try:
        return json.loads(path.read_text(encoding="utf-8-sig")), "parsed"
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, "invalid"


def _valid_pip_payload(payload: Any) -> bool:
    if not isinstance(payload, dict) or not isinstance(payload.get("dependencies"), list):
        return False
    for dependency in payload["dependencies"]:
        if (
            not isinstance(dependency, dict)
            or not isinstance(dependency.get("name"), str)
            or not dependency["name"].strip()
            or not isinstance(dependency.get("version"), str)
            or not dependency["version"].strip()
            or not isinstance(dependency.get("vulns"), list)
        ):
            return False
        for vulnerability in dependency["vulns"]:
            if (
                not isinstance(vulnerability, dict)
                or not isinstance(vulnerability.get("id"), str)
                or not vulnerability["id"].strip()
            ):
                return False
            aliases = vulnerability.get("aliases", [])
            fixed_versions = vulnerability.get("fix_versions", [])
            severity = vulnerability.get("severity")
            if (
                not isinstance(aliases, list)
                or any(not isinstance(alias, str) or not alias.strip() for alias in aliases)
                or not isinstance(fixed_versions, list)
                or any(
                    not isinstance(version, str) or not version.strip()
                    for version in fixed_versions
                )
                or (severity is not None and not isinstance(severity, str))
            ):
                return False
    return True


def _valid_npm_payload(payload: Any) -> bool:
    if not isinstance(payload, dict) or not isinstance(payload.get("vulnerabilities"), dict):
        return False
    for package, vulnerability in payload["vulnerabilities"].items():
        if (
            not isinstance(package, str)
            or not package.strip()
            or not isinstance(vulnerability, dict)
            or not isinstance(vulnerability.get("via"), list)
            or not isinstance(vulnerability.get("range"), str)
            or not isinstance(vulnerability.get("severity"), str)
            or not isinstance(vulnerability.get("fixAvailable"), (bool, dict))
        ):
            return False
        fix_available = vulnerability["fixAvailable"]
        if isinstance(fix_available, dict) and (
            not isinstance(fix_available.get("version"), str)
            or not fix_available["version"].strip()
        ):
            return False
        for item in vulnerability["via"]:
            if isinstance(item, str):
                if not item.strip():
                    return False
                continue
            if not isinstance(item, dict):
                return False
            identifier = item.get("source") or item.get("name")
            if not isinstance(identifier, (int, str)) or not str(identifier).strip():
                return False
    return True


def _valid_npm_lock_payload(payload: Any) -> bool:
    return isinstance(payload, dict) and isinstance(payload.get("packages"), dict)


def _schema_status(payload: Any, load_status: str, *, scanner: str) -> str:
    if load_status != "parsed":
        return load_status
    if scanner == "pip":
        valid = _valid_pip_payload(payload)
    elif scanner == "npm":
        valid = _valid_npm_payload(payload)
    else:
        raise ValueError(f"Unknown dependency scanner: {scanner}")
    return "parsed" if valid else "invalid_schema"


def _pip_findings(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    dependencies = payload.get("dependencies")
    if not isinstance(dependencies, list):
        return []
    findings: list[dict[str, Any]] = []
    for dependency in dependencies:
        if not isinstance(dependency, dict):
            continue
        vulnerabilities = dependency.get("vulns")
        if not isinstance(vulnerabilities, list):
            continue
        advisory_map: dict[tuple[tuple[str, ...], str | None], set[str]] = {}
        for vulnerability in vulnerabilities:
            if not isinstance(vulnerability, dict) or not vulnerability.get("id"):
                continue
            advisory_ids = {str(vulnerability["id"])}
            aliases = vulnerability.get("aliases")
            if isinstance(aliases, list):
                advisory_ids.update(
                    alias
                    for alias in aliases
                    if isinstance(alias, str) and alias.strip()
                )
            fixed_versions = vulnerability.get("fix_versions")
            if not isinstance(fixed_versions, list):
                fixed_versions = []
            severity = vulnerability.get("severity")
            severity_value = severity if isinstance(severity, str) else None
            advisory_key = (tuple(sorted(advisory_ids)), severity_value)
            advisory_map.setdefault(advisory_key, set()).update(
                version
                for version in fixed_versions
                if isinstance(version, str) and version.strip()
            )
        advisories = [
            {
                "advisory_ids": list(advisory_ids),
                "severity": severity,
                "fixed_versions": sorted(fixed_versions),
            }
            for (advisory_ids, severity), fixed_versions in advisory_map.items()
        ]
        if advisories:
            findings.append(
                {
                    "package": str(dependency["name"]),
                    "declared_version": str(dependency.get("version", "unknown")),
                    "advisories": sorted(
                        advisories,
                        key=lambda item: item["advisory_ids"],
                    ),
                }
            )
    return sorted(findings, key=lambda item: item["package"].lower())


def _npm_dependency_type(package: str, lock_payload: Any) -> str:
    if not isinstance(lock_payload, dict):
        return "unknown"
    packages = lock_payload.get("packages")
    if not isinstance(packages, dict):
        return "unknown"
    suffix = f"node_modules/{package}".casefold()
    matches = [
        metadata
        for path, metadata in packages.items()
        if isinstance(path, str)
        and path.replace("\\", "/").casefold().endswith(suffix)
        and isinstance(metadata, dict)
    ]
    if not matches:
        return "unknown"
    return "development" if all(metadata.get("dev") is True for metadata in matches) else "runtime"


def _npm_findings(payload: Any, lock_payload: Any = None) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    vulnerabilities = payload.get("vulnerabilities")
    if not isinstance(vulnerabilities, dict):
        return []
    findings: list[dict[str, Any]] = []
    for package, vulnerability in vulnerabilities.items():
        if not isinstance(vulnerability, dict):
            continue
        advisory_ids: set[str] = set()
        for item in vulnerability.get("via", []):
            if isinstance(item, dict):
                identifier = item.get("source") or item.get("name")
                if identifier:
                    advisory_ids.add(str(identifier))
        fix_available = vulnerability.get("fixAvailable")
        recommended_fixed_version = (
            str(fix_available["version"])
            if isinstance(fix_available, dict)
            and isinstance(fix_available.get("version"), str)
            and fix_available["version"].strip()
            else None
        )
        findings.append(
            {
                "package": str(package),
                "version_range": (
                    str(vulnerability["range"])
                    if isinstance(vulnerability.get("range"), str)
                    else "unknown"
                ),
                "advisory_ids": sorted(advisory_ids),
                "severity": (
                    str(vulnerability["severity"])
                    if isinstance(vulnerability.get("severity"), str)
                    else None
                ),
                "dependency_type": _npm_dependency_type(str(package), lock_payload),
                "recommended_fixed_version": recommended_fixed_version,
            }
        )
    return sorted(findings, key=lambda item: item["package"].lower())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pip", type=Path)
    parser.add_argument("--npm", type=Path)
    parser.add_argument("--npm-lock", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    pip_payload, pip_status = _load(args.pip)
    npm_payload, npm_status = _load(args.npm)
    npm_lock_payload, npm_lock_status = _load(args.npm_lock)
    pip_status = _schema_status(pip_payload, pip_status, scanner="pip")
    npm_status = _schema_status(npm_payload, npm_status, scanner="npm")
    if args.npm is not None and args.npm_lock is not None:
        if npm_lock_status != "parsed" or not _valid_npm_lock_payload(npm_lock_payload):
            npm_status = "invalid_schema"
    report = {
        "scan_status": {
            "pip": pip_status,
            "npm": npm_status,
        },
        "pip": _pip_findings(pip_payload),
        "npm": _npm_findings(npm_payload, npm_lock_payload),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    failed_statuses = {"missing", "invalid", "invalid_schema"}
    return int(pip_status in failed_statuses or npm_status in failed_statuses)


if __name__ == "__main__":
    raise SystemExit(main())
