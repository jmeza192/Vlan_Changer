# Self‑Hosted GitHub Actions Runner (Lab/EVE‑NG)

Use this guide to install and harden a GitHub Actions runner on your lab Linux VM so CI can reach your EVE‑NG switches.

## Prereqs
- Linux VM with outbound HTTPS (443) access to GitHub and L3 reachability to your EVE‑NG device IPs (SSH/22).
- A GitHub repository where you have admin on Settings > Actions > Runners.
- Python not required on the VM (workflow installs it), but `tar`, `curl`, and `systemd` are typical.

## Network Checklist
- Routes: VM must reach all device IPs in `inventory/devices.yml`.
- Firewall: allow outbound TCP 22 to devices; outbound 443 to GitHub; local ephemeral ports.
- DNS: the VM should resolve `github.com` and `api.github.com`.

## 1) Create the runner in GitHub
Repository > Settings > Actions > Runners > New self‑hosted runner

Pick Linux x64, then copy the commands GitHub provides. Example:

```
cd /opt && sudo mkdir -p actions-runner && sudo chown "$USER" actions-runner
cd /opt/actions-runner
curl -o actions-runner.tar.gz -L https://github.com/actions/runner/releases/download/v2.319.1/actions-runner-linux-x64-2.319.1.tar.gz
tar xzf actions-runner.tar.gz

# Replace URL and TOKEN with values from GitHub UI
./config.sh --url https://github.com/OWNER/REPO \
            --token REPLACE_WITH_TOKEN \
            --name lab-runner-01 \
            --labels "self-hosted,linux,network,eve-ng" \
            --unattended

sudo ./svc.sh install
sudo ./svc.sh start
sudo systemctl status actions.runner.*
```

Notes:
- Labels include `self-hosted` (default) and extra `network,eve-ng` for targeting later if needed.
- Service runs as the current user by default; consider a dedicated `runner` user.

## 2) Add repository secrets
Repository > Settings > Secrets and variables > Actions:

- `NETWORK_USERNAME`
- `NETWORK_PASSWORD`
- Optional: `FALLBACK_USER1`, `FALLBACK_PASS1`, `FALLBACK_SECRET1` (and `2`, `3` … if you use them)

No credentials are committed; the workflow writes a transient `.env` from these secrets.

## 3) Update inventory to your lab IPs
Edit `inventory/devices.yml` to match EVE‑NG device addresses reachable from the runner. Example:

```yaml
devices:
  core1:
    host: 192.168.1.197
    device_type: cisco_ios
  edge1:
    host: 192.168.1.198
    device_type: cisco_ios
  edge2:
    host: 192.168.1.199
    device_type: cisco_ios
```

Verify you can SSH from the runner VM (Ubuntu 24.04 / OpenSSH 9.x):

```
# Quick, non-interactive handshake test (no password prompt)
ssh -o StrictHostKeyChecking=no -o NumberOfPasswordPrompts=0 -o ConnectTimeout=5 \
    -o KexAlgorithms=+diffie-hellman-group14-sha1,+diffie-hellman-group-exchange-sha1 \
    -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedAlgorithms=+ssh-rsa \
    "${NETWORK_USERNAME:-admin}@192.168.1.198" -T 'exit' || echo 'SSH reachable (auth not tested)'
```

Some IOSv images only offer legacy SSH algorithms (SHA‑1). OpenSSH 9.x disables those by default. The flags above enable them for this one command.

Recommended per‑host config to avoid long commands (note: add the leading `+` only once for the whole comma‑separated list):

```
mkdir -p ~/.ssh && chmod 700 ~/.ssh
cat >> ~/.ssh/config <<'EOF'
Host iosv-edge1
  HostName 192.168.1.198
  User admin
  # Enable legacy KEX/hostkey for IOSv. The '+' applies to the entire list.
  # Many Ubuntu 24.04 clients no longer support group-exchange-sha1 at all,
  # so prefer just group14-sha1 to avoid "unsupported kex" errors.
  KexAlgorithms +diffie-hellman-group14-sha1
  HostKeyAlgorithms +ssh-rsa
  PubkeyAcceptedAlgorithms +ssh-rsa
  StrictHostKeyChecking no
EOF
chmod 600 ~/.ssh/config

# Then test (no password prompt)
ssh -o NumberOfPasswordPrompts=0 -o ConnectTimeout=5 iosv-edge1 -T 'exit' || echo 'SSH reachable'
```

## 4) First validation run
From the GitHub Actions tab, run the workflow manually (workflow_dispatch) with safe test values, e.g.:

- Device: `edge1`
- Interface: `GigabitEthernet0/1`
- VLAN: `20`
- Skip rollback: `false`
- Environment: `lab`

The network jobs will now target `runs-on: [self-hosted, linux]` and execute on your VM.

## 5) Hardening (recommended)
- Firewall the runner so only GitHub and EVE‑NG subnets are reachable.
- Create a dedicated, non‑privileged `runner` user and directory (`/srv/actions-runner`).
- Enable ephemeral runners if you require stronger isolation.
- Regularly update the runner binary: `./svc.sh stop && ./bin/installdependencies.sh && ./svc.sh start`.

## 6) Troubleshooting quick checks
- Runner online: repo Settings > Actions > Runners shows green dot.
- Logs: `journalctl -u actions.runner* -f` on the VM.
- Connectivity: `nc -zv <device-ip> 22` from the VM.
- Auth: run `python tests/test_vlan_e2e.py --validate-only` locally on the VM if needed.

That’s it—your pipeline can now safely touch the lab switches during CI.
