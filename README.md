# dailybuild

Python migration of the GCT daily autobuild tools.

## Commands

```bash
./autobuild.py install-cron
./autobuild.py run-openwrt --config config/openwrt_v1.00_autobuild.env
./autobuild.py run-openwrt --config config/openwrt_master_autobuild.env
./autobuild.py run-os --config config/gdm7275x_linuxos_master_autobuild.env
./autobuild.py run-zephyros --config config/zephyros_autobuild.env
./autobuild.py upload --run-date 20260512
./autobuild.py notify --run-date 20260512
./autobuild.py test-once
```

For isolated upload validation before Samba or cron rollout:

```bash
./autobuild.py upload --run-date 20260512 \
  --status-file /path/to/daily_autobuild_status_20260512.txt \
  --output-dir /tmp/dailybuild-upload-test

./autobuild.py upload --run-date 20260512 --force

./autobuild.py notify --run-date 20260512 \
  --status-file /path/to/daily_autobuild_status_20260512.txt

./autobuild.py notify --run-date 20260512 --force
```

## Layout

```text
autobuild.py          CLI entrypoint
config/               env-style runtime configs
autobuild/config.py   env/config loading and shared paths
autobuild/runner.py   OpenWrt / OS / Zephyros runner adapters
autobuild/status.py   summary/status parsing and FW_build_info generation
autobuild/upload.py   Samba/local upload packaging
autobuild/mail.py     HTML mail generation and SMTP delivery
autobuild/scheduler.py cron and one-time test adapters
autobuild/gitinfo.py  commit metadata helpers
```

The migration keeps build execution and cron installation compatible with the
existing shell scripts through `LEGACY_AUTOBUILD_DIR` while upload, mail, and
status parsing move into Python first.

This repository is intended to run under the `jamesahn` account and reuse the
existing autobuild checkout, repo workspace, logs, and state directories. The
default paths therefore continue to point at:

```text
/home/jamesahn/gct-build-tools/autobuild
/home/jamesahn/gct_workspace/autobuild
```
