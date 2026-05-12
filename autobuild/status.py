"""Daily status parsing and FW_build_info generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


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
            lines.append(f"  - {title}")
            git_lines = sections.get(key).git_log if key in sections else []
            if git_lines:
                lines.extend(f"    {line}" for line in git_lines)
            else:
                lines.extend([
                    "    commit : N/A",
                    "    author : N/A",
                    "    date   : N/A",
                    "    subject: N/A",
                ])
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
