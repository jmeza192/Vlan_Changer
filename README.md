# VLAN Changer + CI/CD Pipeline

[![CI](https://img.shields.io/github/actions/workflow/status/OWNER/REPO/network-ci-cd.yml?branch=main&label=CI%2FCD)](https://github.com/OWNER/REPO/actions/workflows/network-ci-cd.yml)
[![Python](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://www.python.org/downloads/)

End‑to‑end VLAN change automation with verification, automatic rollback, and a GitHub Actions pipeline. Locates devices by IP or MAC, finds the access switchport (via CDP traversal and port‑channel awareness), applies the VLAN, verifies it, and optionally rolls back.

## Purpose

This tool helps network administrators quickly find a device's switch port and change its VLAN assignment. It automatically traverses the network topology through CDP neighbors to locate access ports, even when devices are connected through multiple network layers.

## Features

- **Multi-site support**: Configure up to 20 different network locations
- **Dual lookup modes**: Find devices by IP address or MAC address
- **Automatic topology traversal**: Follows CDP neighbors through trunks to find access ports
- **Port-channel support**: Handles EtherChannel/port-channel configurations
- **VLAN configuration**: Set both access and voice VLANs
- **Credential fallback**: Multiple authentication credential sets
- **Smart retry logic**: Adaptive timing for slow switches
- **Configuration verification**: Confirms changes were applied correctly
- **Automatic saving**: Saves configuration to switch memory

## Prerequisites

- Python 3.9+
- Install deps: `pip install -r requirements.txt`
  - netmiko, python-dotenv, PyYAML, pytest

## Configuration

1. Create a `.env` file in the same directory as the script (use `.env.example` as template)
2. Configure primary credentials:
   ```
   PRIMARY_USERNAME=your_username
   PRIMARY_PASSWORD=your_password
   ```
3. Configure fallback credentials (optional but recommended):
   ```
   FALLBACK_USER1=backup_username
   FALLBACK_PASS1=backup_password
   FALLBACK_SECRET1=enable_password
   ```
4. (Optional) Configure network locations for interactive mode (up to 20 sites):
   ```
   VLAN_LOCATION_1_NAME=Main Office
   VLAN_LOCATION_1_IP=192.168.1.1
   VLAN_LOCATION_2_NAME=Branch Office
   VLAN_LOCATION_2_IP=192.168.2.1
   ```

## Usage (Interactive)

```bash
python VlanChange.py
```

The script will prompt you to:
1. Select a network site
2. Choose lookup method (IP or MAC address)
3. Enter the device identifier
4. Specify new access VLAN
5. Optionally specify voice VLAN
6. Confirm the changes

## Usage (Non‑Interactive, for CI or scripts)

```bash
python VlanChange.py \
  --device-ip 192.168.1.198 \
  --interface GigabitEthernet0/1 \
  --access-vlan 20 \
  [--voice-vlan 30]
```

Returns exit code 0 on success. Uses credentials from `.env` (locally) or Action secrets (in CI).

## Example Session (Interactive)

```
Select site:
 1) Main Office    192.168.1.1
 2) Branch Office  192.168.2.1
Enter choice 1-20: 1

Lookup by IP or MAC? (ip/mac): ip
Device IP: 192.168.1.100

✔ Connected to 192.168.1.1 as admin
↳ ARP: 192.168.1.100 → 001a.2b3c.4d5e

✓ Device found on 192.168.1.10  port Gi1/0/24

Access VLAN (blank cancels): 100
Voice VLAN (Enter to skip): 200
CONFIRM Gi1/0/24 → access 100, voice 200? (y/N): y

Pushing config …
✔ Configuration saved successfully
✔ Done.
```

## How It Works

1. **Device Location**: 
   - For IP lookup: Finds MAC address in ARP table
   - For MAC lookup: Uses provided MAC address
   
2. **Port Discovery**:
   - Searches MAC address table on core switches
   - If found on trunk port, follows CDP neighbors
   - Continues until access port is found
   - Handles port-channel configurations

3. **VLAN Configuration**:
   - Tests switch responsiveness and adapts timing
   - Applies configuration with verification
   - Retries failed commands automatically
   - Saves configuration to memory

## Switch Compatibility

- Cisco IOS/IOS-XE switches
- Supports various interface naming conventions (Gi, Fa, Te, etc.)
- Handles different CDP output formats
- Adapts to switch response times automatically

## Error Handling

- Multiple credential fallback options
- Automatic retry logic for slow switches
- Configuration verification before completion
- Detailed error messages and debugging output
- Graceful handling of network topology changes

## CI/CD Pipeline (GitHub Actions)

- Workflow: `.github/workflows/network-ci-cd.yml`
- Triggers: `workflow_dispatch`, scheduled, and PRs (network steps run on self‑hosted only)

Jobs overview:
- Static checks: syntax/import checks on GitHub‑hosted runner
- Validate environment: attempts device connectivity (`tests/test_vlan_e2e.py --validate-only`)
- Pre‑change audit: captures baseline (`tests/network_audit.py --report`)
- Execute VLAN change: runs full `VlanChange.py` in non‑interactive mode, verifies, sets outputs
- Rollback (optional): reverts to original access VLAN unless `skip_rollback` is true
- Post‑change validation: captures post state and compares to baseline
- Final report: aggregates results and artifacts

Artifacts:
- `vlanchange_run.log`, `test_report_*.md`, `*_audit_*.json`, `comparison_report.txt`

To run in Actions:
1) Update `inventory/devices.yml` and `inventory/targets.yml` to your lab.
2) Add secrets: `NETWORK_USERNAME`, `NETWORK_PASSWORD` (+ optional `FALLBACK_*`).
3) Ensure a self‑hosted runner can reach device IPs over SSH.
4) Use “Run workflow” and set device/interface/VLAN, or rely on repo defaults.

Self‑hosted runner tips:
- Outbound 22 to lab devices and 443 to GitHub
- Add legacy SSH algorithms if using IOSv images (OpenSSH 9+ may need `+diffie-hellman-group14-sha1`, `+ssh-rsa`)

## Inventory & Secrets

- `inventory/devices.yml`: device names and IPs
- `inventory/targets.yml`: target device/interface and `test_vlan`
- Secrets (Actions): `NETWORK_USERNAME`, `NETWORK_PASSWORD`, optional `FALLBACK_USER{N}`, `FALLBACK_PASS{N}`, `FALLBACK_SECRET{N}`
- Local: copy `.env.example` to `.env` and fill in credentials for local runs

## Safety Features

- Pre/post audits and explicit on‑box verification
- Optional automatic rollback to original VLAN
- Adaptive timing and retries for slow switches
- Credentials injected at runtime (no secrets in repo)

## Troubleshooting

- Connectivity: ensure the self‑hosted runner reaches device IPs (`nc -zv <ip> 22`)
- Auth: verify secrets are set; try `python tests/test_vlan_e2e.py --validate-only`
- Prompt quirks: Netmiko base prompt is normalized; command verification disabled where necessary
