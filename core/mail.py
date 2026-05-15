"""Daily report mail generation and SMTP delivery."""

from __future__ import annotations

import datetime as dt
import smtplib
import ssl
from email.message import EmailMessage
from html import escape
from pathlib import Path
from types import SimpleNamespace

from .config import DailybuildPaths, daily_status_file, load_env_file, merged_env, today
from .lock import LockDir, LockHeld
from .status import parse_status_file
from . import upload
from .upload import safe_name, upload_subdir


_FAILURE_BLOCK_START = "[Failure analysis]"
_RECENT_ERRORS_START = "[Recent errors]"


def _manifest_block(section_name: str, fields: dict[str, str]) -> str:
    if "OpenWrt " not in section_name:
        return ""
    lines = []
    for key in ("GDM", "SBL", "UBOOT"):
        value = fields.get(key, "")
        if value:
            lines.append(f"{key} : {value}")
    return "\n".join(lines)


def _split_model_item(section_name: str) -> tuple[str, str]:
    parts = section_name.split(maxsplit=1)
    if len(parts) == 2 and parts[0].startswith("GDM"):
        return parts[0], parts[1]
    if section_name.startswith("OpenWrt ") or section_name == "Zephyros":
        return "GDM7275X", section_name
    return "Other", section_name


def _upload_dir_name(section_name: str, item_name: str) -> str:
    if item_name == "OpenWrt v1.00":
        return "GDM7275X\\openwrt_v100"
    if item_name == "OpenWrt master":
        return "GDM7275X\\openwrt_master"
    if item_name == "Linuxos master":
        return "GDM7275X\\linuxos_master"
    if item_name == "Zephyros":
        return "GDM7275X\\Zephyros"
    lowered = section_name.lower()
    if "gdm7243st" in lowered:
        return "GDM7243ST\\uTKernel"
    if "gdm7243a" in lowered:
        return "GDM7243A\\uTKernel"
    if "gdm7243i" in lowered:
        return "GDM7243i\\zephyr_v2.3"
    return safe_name(section_name)


def _unc_join(root: str, subdir: Path, rel_path: str) -> str:
    pieces = [root.rstrip("\\")]
    pieces.extend(subdir.parts)
    pieces.extend(part for part in rel_path.split("\\") if part)
    return "\\".join(pieces)


def _failure_analysis(fields: dict[str, str]) -> str:
    value = fields.get("Failure analysis", "").strip()
    if value:
        return value
    value = fields.get("Fail reason", "").strip()
    if value:
        return value
    report_path = fields.get("Failure rpt", "").strip()
    if not report_path:
        return ""
    report_file = Path(report_path)
    if not report_file.is_file():
        return ""
    lines = report_file.read_text(encoding="utf-8", errors="replace").splitlines()
    in_block = False
    collected: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped == _FAILURE_BLOCK_START:
            in_block = True
            continue
        if in_block and stripped == _RECENT_ERRORS_START:
            break
        if in_block:
            if stripped:
                collected.append(stripped)
            continue
        if stripped.startswith("Fail reason"):
            _, _, tail = stripped.partition(":")
            fallback = tail.strip()
            if fallback:
                return fallback
    return " ".join(collected).strip()


def build_html(status_file: Path, subject: str, run_date: str, samba_unc_root: str, upload_target_subdir: Path | None = None) -> str:
    upload_target_subdir = upload_target_subdir or Path(run_date)
    groups: dict[str, list[tuple[str, str]]] = {}
    for section in parse_status_file(status_file):
        model, item = _split_model_item(section.name)
        result = section.fields.get("Result", "UNKNOWN")
        duration = section.fields.get("Duration", "")
        failure_analysis = _failure_analysis(section.fields)
        status_color = "#177245" if result == "SUCCESS" else "#b42318" if result == "FAIL" else "#475467"
        status_bg = "#ecfdf3" if result == "SUCCESS" else "#fef3f2" if result == "FAIL" else "#f2f4f7"
        upload_root = samba_unc_root.rstrip("\\")
        rel_upload_dir = _upload_dir_name(section.name, item)
        log_path = _unc_join(upload_root, upload_target_subdir, f"{rel_upload_dir}\\Log") if upload_root else ""
        image_path = _unc_join(upload_root, upload_target_subdir, f"{rel_upload_dir}\\Image") if upload_root and result == "SUCCESS" else ""
        git_block = "\n".join(escape(line) for line in section.git_log)
        manifest_block = escape(_manifest_block(section.name, section.fields))
        details = []
        if duration:
            details.append(f"<div><strong>Duration:</strong> {escape(duration)}</div>")
        if git_block:
            details.append("<div><strong>Last commit:</strong></div><pre style='margin:4px 0 0 18px;padding:8px 10px;background:#f8fafc;border:1px solid #e4e7ec;border-radius:6px;font-family:Consolas,Menlo,monospace;font-size:12px;line-height:1.45;color:#344054;white-space:pre-wrap;'>" + git_block + "</pre>")
        if manifest_block:
            details.append("<div><strong>Manifest hash:</strong></div><pre style='margin:4px 0 0 18px;padding:8px 10px;background:#f8fafc;border:1px solid #e4e7ec;border-radius:6px;font-family:Consolas,Menlo,monospace;font-size:12px;line-height:1.45;color:#344054;white-space:pre-wrap;'>" + manifest_block + "</pre>")
        if failure_analysis:
            details.append(f"<div><strong>Failure analysis:</strong> {escape(failure_analysis)}</div>")
        if log_path:
            details.append(f"<div><strong>Log :</strong> <span style='font-family:monospace;color:#0b63ce;'>{escape(log_path)}</span></div>")
        if image_path:
            details.append(f"<div><strong>Image :</strong> <span style='font-family:monospace;color:#0b63ce;'>{escape(image_path)}</span></div>")
        card = (
            "<div style='border:1px solid #e4e7ec;border-radius:8px;padding:14px 16px;background:#ffffff;margin:10px 0 0 18px;'>"
            "<div style='display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:10px;'>"
            f"<div style='font-size:15px;font-weight:700;color:#101828;'>- {escape(item.replace('OpenWrt', 'OpenWRT', 1))}</div>"
            f"<div style='padding:4px 10px;border-radius:999px;background:{status_bg};color:{status_color};font-size:12px;font-weight:700;white-space:nowrap;'>{escape(result)}</div>"
            "</div><div style='font-size:13px;line-height:1.6;color:#344054;'>"
            + "".join(details)
            + "</div></div>"
        )
        groups.setdefault(model, []).append((item, card))

    order = {"GDM7275X": 0, "GDM7243A": 1, "GDM7243ST": 2, "GDM7243i": 3}
    item_order = {"OpenWrt v1.00": 0, "OpenWrt master": 1, "Linuxos master": 2, "Zephyros": 3}
    model_cards = []
    for model in sorted(groups, key=lambda name: (order.get(name, 99), name)):
        items = sorted(groups[model], key=lambda item: (item_order.get(item[0], 99), item[0]))
        model_cards.append(
            "<div style='border:1px solid #d0d5dd;border-radius:10px;background:#f8fafc;margin-bottom:14px;padding:16px;'>"
            "<div style='display:flex;align-items:center;justify-content:space-between;gap:12px;'>"
            f"<div style='font-size:18px;font-weight:800;color:#101828;'>{escape(model)}</div>"
            f"<div style='font-size:12px;font-weight:700;color:#475467;background:#ffffff;border:1px solid #e4e7ec;border-radius:999px;padding:4px 10px;'>{len(items)} items</div>"
            "</div><div style='border-left:2px solid #d0d5dd;margin-top:12px;'>"
            + "".join(card for _, card in items)
            + "</div></div>"
        )

    return f"""<html><body style="margin:0;padding:24px;background:#f8fafc;font-family:'Segoe UI',Arial,sans-serif;color:#101828;">
<div style="max-width:860px;margin:0 auto;">
<div style="background:#0f172a;border-radius:16px;padding:24px 28px;color:#ffffff;margin-bottom:16px;">
<div style="font-size:13px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;opacity:0.88;">GCT-CS</div>
<div style="font-size:28px;font-weight:800;margin-top:6px;">Daily build report</div>
<div style="font-size:14px;opacity:0.9;margin-top:8px;">Generated from the CS-buildserver</div>
</div>
<div style="background:#ffffff;border:1px solid #eaecf0;border-radius:16px;padding:20px 20px 8px;margin-bottom:16px;">
<div style="font-size:18px;font-weight:700;margin-bottom:14px;">{escape(subject.replace('GCT-CS Daily Build Report - ', ''))} - Build Test Summary</div>
{''.join(model_cards) if model_cards else "<div style='color:#475467;'>No parsed sections found.</div>"}
</div></div></body></html>"""


def notify(args) -> int:
    run_date = args.run_date or today()
    overrides = {"RUN_DATE": run_date}
    if getattr(args, "status_file", None):
        overrides["DAILY_STATUS_FILE"] = args.status_file
    if getattr(args, "min_run_ts", None):
        overrides["MIN_RUN_TS"] = args.min_run_ts
    env = merged_env(args.config, overrides)
    paths = DailybuildPaths.from_env(env)
    lock_dir = Path(env.get("LOCK_DIR") or paths.tmp_root / f"dailybuild_mail_notifier_{run_date}.lock")
    try:
        with LockDir(lock_dir):
            return _notify_with_lock(args, env, run_date)
    except LockHeld:
        print("[INFO] Daily mail notifier skipped: another notifier run is in progress")
        return 0


def _notify_with_lock(args, env: dict[str, str], run_date: str) -> int:
    if env.get("EMAIL_NOTI_ENABLED", "0") != "1":
        print(f"[INFO] Daily mail notifier skipped: EMAIL_NOTI_ENABLED={env.get('EMAIL_NOTI_ENABLED')}")
        return 0

    paths = DailybuildPaths.from_env(env)
    sent_flag = Path(env.get("SENT_FLAG_FILE") or paths.state_root / f".dailybuild_mail_sent_{run_date}.flag")
    upload_flag = Path(env.get("UPLOAD_FLAG_FILE") or paths.state_root / f".dailybuild_logs_uploaded_{run_date}.flag")
    if sent_flag.exists() and not getattr(args, "force", False):
        print(f"[INFO] Daily mail notifier skipped: already sent for RUN_DATE={run_date}")
        return 0

    status_file = daily_status_file(env, run_date)
    if not status_file.exists():
        print(f"[WARN] Daily mail notifier skipped: daily status file not found: {status_file}")
        return 0

    if not getattr(args, "status_file", None) and not summaries_ready_for_today(env, run_date):
        return 0

    if not upload_flag.exists():
        upload.run(SimpleNamespace(
            run_date=run_date,
            config=getattr(args, "config", "config/dailybuild_common.env"),
            status_file=getattr(args, "status_file", None),
            output_dir=None,
            upload_subdir=env.get("SAMBA_UPLOAD_SUBDIR"),
            force=False,
        ))

    smtp_host = env.get("SMTP_HOST", "")
    mail_from = env.get("MAIL_FROM") or env.get("SMTP_USER", "")
    recipients = [addr.strip() for addr in env.get("MAIL_TO", "").split(",") if addr.strip()]
    if not smtp_host or not mail_from or not recipients:
        print("[WARN] Daily mail notifier skipped: SMTP_HOST, MAIL_FROM, or MAIL_TO is not set")
        return 0

    subject = env.get("REPORT_SUBJECT_PREFIX", "") + f" GCT-CS Daily Build Report - {dt.datetime.now().strftime('%m/%d/%Y')}"
    subject = subject.strip()
    msg = EmailMessage()
    msg["Subject"] = subject
    from_name = env.get("MAIL_FROM_NAME", "").strip()
    msg["From"] = f"{from_name} <{mail_from}>" if from_name else mail_from
    msg["To"] = ", ".join(recipients)
    if env.get("MAIL_REPLY_TO"):
        msg["Reply-To"] = env["MAIL_REPLY_TO"]
    msg.set_content("GCT-CS Daily Build Report\n\nPlease view the HTML email for the model-grouped build summary.")
    msg.add_alternative(build_html(status_file, subject, run_date, env.get("SAMBA_UPLOAD_UNC_ROOT", ""), upload_subdir(env, run_date)), subtype="html")

    ctx = ssl.create_default_context()
    if env.get("SMTP_INSECURE_TLS", "0") == "1":
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    with smtplib.SMTP(smtp_host, int(env.get("SMTP_PORT", "587")), timeout=30) as smtp:
        smtp.ehlo()
        if env.get("SMTP_USE_STARTTLS", "1") == "1":
            smtp.starttls(context=ctx)
            smtp.ehlo()
        if env.get("SMTP_USER") or env.get("SMTP_PASSWORD"):
            smtp.login(env.get("SMTP_USER", ""), env.get("SMTP_PASSWORD", ""))
        smtp.send_message(msg)

    sent_flag.parent.mkdir(parents=True, exist_ok=True)
    sent_flag.write_text(f"sent_at={dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\nrun_date={run_date}\n", encoding="utf-8")
    print(f"[INFO] Daily mail notifier sent to: {','.join(recipients)}")
    return 0


SUMMARY_FILES = [
    ("v1.00", "V100_SUMMARY_FILE", "openwrt/v1.00/latest_summary.env"),
    ("master", "MASTER_SUMMARY_FILE", "openwrt/master/latest_summary.env"),
    ("Zephyros", "ZEPHYROS_SUMMARY_FILE", "zephyros/latest_summary.env"),
    ("GDM7275X Linuxos master", "GDM7275X_LINUXOS_SUMMARY_FILE", "linuxos/gdm7275x/latest_summary.env"),
    ("GDM7243A uTKernel", "GDM7243A_UTKERNEL_SUMMARY_FILE", "uTKernel/gdm7243a/latest_summary.env"),
    ("GDM7243ST uTKernel", "GDM7243ST_UTKERNEL_SUMMARY_FILE", "uTKernel/gdm7243st/latest_summary.env"),
    ("GDM7243i zephyr-v2.3", "GDM7243I_ZEPHYR_SUMMARY_FILE", "zephyr_v2_3/gdm7243i/latest_summary.env"),
]


def summaries_ready_for_today(env: dict[str, str], run_date: str) -> bool:
    log_root = DailybuildPaths.from_env(env).log_root
    for label, env_key, rel_path in SUMMARY_FILES:
        summary_file = Path(env.get(env_key) or log_root / rel_path)
        if not summary_ready_for_today(summary_file, run_date, env.get("MIN_RUN_TS", "")):
            print(f"[INFO] Daily mail notifier waiting: {label} summary is not ready for {run_date}")
            return False
    return True


def summary_ready_for_today(summary_file: Path, run_date: str, min_run_ts: str = "") -> bool:
    if not summary_file.exists():
        return False
    summary = load_env_file(summary_file)
    run_ts = summary.get("RUN_TS", "")
    if not run_ts or run_ts.split("_", 1)[0] != run_date:
        return False
    if min_run_ts and run_ts < min_run_ts:
        return False
    return bool(summary.get("BUILD_RESULT") and summary.get("BUILD_ENDED_AT"))
