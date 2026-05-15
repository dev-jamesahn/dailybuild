"""Daily status parsing and FW_build_info generation."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

from .config import DailybuildPaths, daily_status_file, load_env_file, merged_env, today


@dataclass
class StatusSection:
    name: str
    fields: dict[str, str] = field(default_factory=dict)
    git_log: list[str] = field(default_factory=list)


def parse_status_file(path: str | Path) -> list[StatusSection]:
    sections: list[StatusSection] = []
    current: StatusSection | None = None
    in_git = False

    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.rstrip("\n")
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            current = StatusSection(stripped[1:-1])
            sections.append(current)
            in_git = False
            continue
        if current is None:
            continue
        if line.startswith("Git log"):
            in_git = True
            continue
        if in_git and line.startswith("  "):
            current.git_log.append(line.strip())
            continue
        if in_git and stripped:
            in_git = False
        if ":" in line:
            key, value = line.split(":", 1)
            current.fields[key.strip()] = value.strip()

    return sections


FW_BUILD_INFO_ORDER = [
    ("GDM7275X", [
        ("OpenWRT v1.00", "GDM7275X OpenWrt v1.00"),
        ("OpenWRT master", "GDM7275X OpenWrt master"),
        ("Linuxos master", "GDM7275X Linuxos master"),
        ("Zephyros", "GDM7275X Zephyros"),
    ]),
    ("GDM7243A", [("uTKernel - gdm7243a_no_l2", "GDM7243A uTKernel - gdm7243a_no_l2")]),
    ("GDM7243ST", [("uTKernel - gdm7243mt_32mb_no_l2_vport14", "GDM7243ST uTKernel - gdm7243mt_32mb_no_l2_vport14")]),
    ("GDM7243i", [("zephyr-v2.3 - gdm7243i_nbiot_ntn_quad", "GDM7243i zephyr-v2.3 - gdm7243i_nbiot_ntn_quad")]),
]


def generate_fw_build_info(status_file: str | Path) -> str:
    sections = {section.name: section for section in parse_status_file(status_file)}
    lines: list[str] = []

    for model, entries in FW_BUILD_INFO_ORDER:
        lines.append(f"[{model}]")
        lines.append("")
        for title, key in entries:
            section = sections.get(key)
            result = _fw_build_result(section)
            lines.append(f"  - {title} : {result}")
            git_lines = section.git_log if section else []
            if git_lines:
                lines.extend(f"    {line}" for line in git_lines)
            else:
                lines.extend([
                    "    commit : N/A",
                    "    author : N/A",
                    "    date   : N/A",
                    "    subject: N/A",
                ])
            failure_analysis = section.fields.get("Failure analysis", "") if section else ""
            if result == "FAIL" and failure_analysis:
                lines.append(f"    Failure analysis : {failure_analysis}")
            lines.append("")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _fw_build_result(section: StatusSection | None) -> str:
    if section is None:
        return "N/A"
    result = section.fields.get("Result") or section.fields.get("Status") or "UNKNOWN"
    if result == "SUCCESS":
        return "PASS"
    if result == "FAIL":
        return "FAIL"
    return result


DEFAULT_SUMMARY_FILES = [
    ("OpenWrt v1.00", "openwrt/v1.00/latest_summary.env"),
    ("OpenWrt master", "openwrt/master/latest_summary.env"),
    ("Zephyros", "zephyros/latest_summary.env"),
]


def format_target_status(label: str, summary_path: str | Path, not_run_if_missing: bool = False) -> str:
    summary_file = Path(summary_path)
    if not summary_file.exists():
        if not_run_if_missing:
            return f"[{label}]\nStatus       : NOT_RUN\n\n"
        return ""

    summary = load_env_file(summary_file)
    target_name = summary.get("TARGET_NAME") or label
    lines = [
        f"[{target_name}]",
        f"Result       : {summary.get('BUILD_RESULT', 'UNKNOWN')}",
        f"Current stage: {summary.get('CURRENT_STAGE', '')}",
        f"Started      : {summary.get('BUILD_STARTED_AT', '')}",
        f"Ended        : {summary.get('BUILD_ENDED_AT', '')}",
        f"Duration     : {summary.get('BUILD_DURATION_FMT', '')}",
        f"Run ts       : {summary.get('RUN_TS', '')}",
        f"Log path     : {summary.get('BUILD_LOG', '')}",
    ]
    if summary.get("FAIL_REASON"):
        lines.append(f"Fail reason  : {summary['FAIL_REASON']}")
    if summary.get("FAILURE_ANALYSIS"):
        lines.append(f"Failure analysis: {summary['FAILURE_ANALYSIS']}")
    if summary.get("MAIN_REPO_LAST_COMMIT") or summary.get("MAIN_REPO_LAST_SUBJECT"):
        lines.extend([
            "Git log      :",
            f"  commit : {summary.get('MAIN_REPO_LAST_COMMIT', '')}",
            f"  author : {summary.get('MAIN_REPO_LAST_AUTHOR', '')}",
            f"  date   : {summary.get('MAIN_REPO_LAST_DATE', '')}",
            f"  subject: {summary.get('MAIN_REPO_LAST_SUBJECT', '')}",
        ])
    manifest = _manifest_hashes(summary)
    if manifest and "Zephyros" not in target_name:
        lines.extend([
            "Manifest hashes:",
            f"  GDM   : {manifest.get('GDM', '')}",
            f"  SBL   : {manifest.get('SBL', '')}",
            f"  UBOOT : {manifest.get('UBOOT', '')}",
        ])
    return "\n".join(lines) + "\n\n"


def generate_daily_status(log_root: str | Path, generated_at: dt.datetime | None = None) -> str:
    root = Path(log_root)
    generated_at = generated_at or dt.datetime.now()
    chunks = [
        "==========================================",
        "Daily Autobuild Status",
        f"Generated at : {generated_at.strftime('%Y-%m-%d %H:%M:%S')}",
        "==========================================",
        "",
    ]
    body = "\n".join(chunks) + "\n"
    for label, rel_path in DEFAULT_SUMMARY_FILES:
        body += format_target_status(label, root / rel_path, not_run_if_missing=True)
    for summary_file in discover_os_summary_files(root):
        body += format_target_status("OS Autobuild", summary_file)
    return body


def discover_os_summary_files(log_root: str | Path) -> list[Path]:
    root = Path(log_root)
    if not root.exists():
        return []
    skipped_parts = {"openwrt", "zephyros"}
    results = []
    for path in sorted(root.glob("*/*/latest_summary.env")):
        rel_parts = set(path.relative_to(root).parts)
        if rel_parts & skipped_parts:
            continue
        results.append(path)
    return results


def write_daily_status_command(args) -> int:
    run_date = args.run_date or today()
    overrides = {"RUN_DATE": run_date}
    if getattr(args, "output", None):
        overrides["DAILY_STATUS_FILE"] = args.output
    env = merged_env(args.config, overrides)
    paths = DailybuildPaths.from_env(env)
    output = Path(args.output) if getattr(args, "output", None) else daily_status_file(env, run_date)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(generate_daily_status(paths.log_root), encoding="utf-8")
    print(f"[INFO] Daily status file generated: {output}")
    return 0


def _manifest_hashes(summary: dict[str, str]) -> dict[str, str]:
    values = {
        "GDM": summary.get("MANIFEST_GDM_COMMIT", ""),
        "SBL": summary.get("MANIFEST_SBL_COMMIT", ""),
        "UBOOT": summary.get("MANIFEST_UBOOT_COMMIT", ""),
    }
    hash_log = summary.get("HASH_LOG")
    if hash_log:
        for key, parsed in _read_hash_log(hash_log).items():
            values[key] = values.get(key) or parsed
    return {key: value for key, value in values.items() if value}


def _read_hash_log(path: str | Path) -> dict[str, str]:
    hash_file = Path(path)
    if not hash_file.exists():
        return {}
    values: dict[str, str] = {}
    for line in hash_file.read_text(encoding="utf-8").splitlines():
        parts = line.split("|")
        if len(parts) >= 3 and parts[0] in {"GDM", "SBL", "UBOOT"}:
            values.setdefault(parts[0], parts[2])
    return values
