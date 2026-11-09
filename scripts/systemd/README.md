# Optional: run the local dev stack as a systemd user service

`tracemap-dev.service` is a **template**, committed for review. Nothing in this
repository installs it for you, and it deliberately targets a *user* unit so it
never requires `sudo` or a system-wide daemon.

> Scope: local development only. The service runs `TRACEMAP_ENV=development`
> with the insecure `dev-<name>` identity and listens on `127.0.0.1` only. Do
> not enable lingering for a multi-user machine and do not front it with a
> reverse proxy.

## Install (per user)

```bash
REPO=/absolute/path/to/TraceMap
mkdir -p ~/.config/systemd/user
sed "s#__REPO__#$REPO#g" "$REPO/scripts/systemd/tracemap-dev.service" \
  > ~/.config/systemd/user/tracemap-dev.service
systemctl --user daemon-reload
systemctl --user enable --now tracemap-dev.service
systemctl --user status tracemap-dev.service
```

Logs are still written to `$TRACEMAP_RUNTIME_DIR/logs` (default
`~/tracemap-runtime/logs`), so `scripts/dev-status.sh` keeps working.

## Operate

```bash
systemctl --user restart tracemap-dev.service   # equivalent to stop + start
systemctl --user stop tracemap-dev.service
curl -fsS http://127.0.0.1:8000/health
```

## Uninstall

```bash
systemctl --user disable --now tracemap-dev.service
rm -f ~/.config/systemd/user/tracemap-dev.service
systemctl --user daemon-reload
```

Removing the unit does **not** delete runtime data. To clear local data, see
"Clean up test environments" in `docs/DEPLOYMENT_LINUX.md`.
