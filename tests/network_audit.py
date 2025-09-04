#!/usr/bin/env python3
"""
Network Audit Script for CI/CD Pipeline

This script captures the current state of network devices before and after changes
to ensure proper validation and enable rollback if needed.

Key Functions:
1. Captures port configurations across all devices
2. Records VLAN assignments and port states
3. Documents CDP neighbors and port channel memberships
4. Generates baseline reports for comparison
5. Validates post-change state against expectations
"""

import json
import re
import yaml
import sys
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict
from datetime import datetime

# Add parent directory to path to import VlanChange modules
sys.path.append(str(Path(__file__).parent.parent))
from VlanChange import connect_with_fallback, get_po_members

@dataclass
class PortConfig:
    """Data class to store port configuration details"""
    interface: str
    admin_status: str
    operational_status: str
    access_vlan: str
    voice_vlan: str
    mode: str  # access, trunk, dynamic
    portfast: bool
    description: str
    speed: str
    duplex: str
    cdp_neighbor: Optional[str] = None
    portchannel_member: Optional[str] = None

@dataclass
class DeviceState:
    """Data class to store complete device state"""
    hostname: str
    ip_address: str
    device_type: str
    timestamp: str
    ports: Dict[str, PortConfig]
    vlans: List[Dict[str, str]]
    portchannels: Dict[str, List[str]]

class NetworkAuditor:
    """Main class for network auditing operations"""
    
    def __init__(self, devices_file: str = "inventory/devices.yml"):
        """Initialize the auditor with device inventory"""
        self.devices_file = Path(devices_file)
        self.devices = self._load_devices()
        self.credentials = self._load_credentials()
        
    def _load_devices(self) -> Dict[str, Dict[str, str]]:
        """Load device inventory from YAML file"""
        try:
            with open(self.devices_file, 'r') as f:
                data = yaml.safe_load(f)
                return data.get('devices', {})
        except FileNotFoundError:
            print(f"❌ Device inventory file not found: {self.devices_file}")
            sys.exit(1)
        except yaml.YAMLError as e:
            print(f"❌ Error parsing device inventory: {e}")
            sys.exit(1)
    
    def _load_credentials(self) -> Tuple[str, str]:
        """Load credentials from environment variables"""
        from dotenv import load_dotenv
        load_dotenv()
        
        username = os.getenv('PRIMARY_USERNAME')
        password = os.getenv('PRIMARY_PASSWORD')
        
        if not username or not password:
            print("❌ Error: PRIMARY_USERNAME and PRIMARY_PASSWORD must be set in .env file")
            sys.exit(1)
            
        return username, password
    
    def get_port_config(self, conn, interface: str) -> PortConfig:
        """Extract detailed configuration for a specific port"""
        print(f"  📋 Gathering config for {interface}...")
        
        # Get switchport information
        switchport_output = conn.send_command(
            f"show interface {interface} switchport",
            read_timeout=30,
            cmd_verify=False
        )
        
        # Get interface status
        status_output = conn.send_command(
            f"show interface {interface} status",
            read_timeout=30,
            cmd_verify=False
        )
        
        # Get running config for the interface
        config_output = conn.send_command(
            f"show running-config interface {interface}",
            read_timeout=30,
            cmd_verify=False
        )
        
        # Parse the outputs
        port_config = PortConfig(
            interface=interface,
            admin_status="unknown",
            operational_status="unknown", 
            access_vlan="1",
            voice_vlan="none",
            mode="unknown",
            portfast=False,
            description="",
            speed="auto",
            duplex="auto"
        )
        
        # Parse switchport output
        for line in switchport_output.splitlines():
            line = line.strip()
            if "Administrative Mode:" in line:
                port_config.mode = line.split()[-1]
            elif "Access Mode VLAN:" in line:
                # Handle formats like: "Access Mode VLAN: 10 (VLAN0010)"
                m = re.search(r"Access Mode VLAN:\s*(\d+)", line)
                if m:
                    port_config.access_vlan = m.group(1)
                else:
                    # Fallback to last token
                    port_config.access_vlan = line.split()[-1]
            elif "Voice VLAN:" in line:
                m = re.search(r"Voice VLAN:\s*(\d+|none)", line, re.I)
                if m:
                    port_config.voice_vlan = m.group(1).lower()
                else:
                    port_config.voice_vlan = line.split()[-1]
        
        # Parse status output
        for line in status_output.splitlines():
            if interface in line:
                parts = line.split()
                if len(parts) >= 3:
                    port_config.operational_status = parts[1] if len(parts) > 1 else "unknown"
                    port_config.admin_status = parts[2] if len(parts) > 2 else "unknown"
                break
        
        # Parse running config
        in_interface = False
        for line in config_output.splitlines():
            line = line.strip()
            if f"interface {interface}" in line:
                in_interface = True
                continue
            elif line.startswith("interface ") and in_interface:
                break
            elif in_interface:
                if "description " in line:
                    port_config.description = line.replace("description ", "")
                elif "spanning-tree portfast" in line:
                    port_config.portfast = True
                elif "speed " in line:
                    port_config.speed = line.split()[-1]
                elif "duplex " in line:
                    port_config.duplex = line.split()[-1]
        
        return port_config
    
    def get_device_ports(self, conn) -> List[str]:
        """Get list of all ports on the device"""
        print("  🔍 Discovering interfaces...")
        
        # Try different commands to get interface list
        commands = [
            "show ip interface brief",
            "show interface status",
            "show interface summary"
        ]
        
        interfaces = []
        for cmd in commands:
            try:
                output = conn.send_command(cmd, read_timeout=30, cmd_verify=False)
                
                for line in output.splitlines():
                    # Look for interface names (GigabitEthernet, FastEthernet, etc.)
                    if any(prefix in line for prefix in ['GigabitEthernet', 'FastEthernet', 'TenGigabitEthernet', 'Ethernet']):
                        parts = line.split()
                        if parts:
                            interface = parts[0]
                            # Avoid management interfaces and virtual interfaces
                            if not any(skip in interface.lower() for skip in ['vlan', 'loopback', 'tunnel', 'mgmt']):
                                if interface not in interfaces:
                                    interfaces.append(interface)
                break
            except Exception as e:
                print(f"  ⚠️ Command '{cmd}' failed: {e}")
                continue
        
        return sorted(interfaces)
    
    def get_device_vlans(self, conn) -> List[Dict[str, str]]:
        """Get VLAN information from the device"""
        print("  🏷️ Gathering VLAN information...")
        
        try:
            output = conn.send_command("show vlan brief", read_timeout=30, cmd_verify=False)
            vlans = []
            
            for line in output.splitlines():
                line = line.strip()
                if line and line[0].isdigit():
                    parts = line.split()
                    if len(parts) >= 2:
                        vlans.append({
                            'id': parts[0],
                            'name': parts[1] if len(parts) > 1 else '',
                            'status': parts[2] if len(parts) > 2 else 'unknown'
                        })
            
            return vlans
        except Exception as e:
            print(f"  ⚠️ Could not get VLAN information: {e}")
            return []
    
    def get_portchannels(self, conn) -> Dict[str, List[str]]:
        """Get port-channel information"""
        print("  🔗 Gathering port-channel information...")
        
        try:
            output = conn.send_command("show etherchannel summary", read_timeout=30, cmd_verify=False)
            portchannels = {}
            
            for line in output.splitlines():
                line = line.strip()
                # Look only at lines that actually reference a Po<number>
                if re.search(r"\bPo\d+\b", line) and not line.startswith(('Flags:', 'Group')):
                    parts = line.split()
                    for part in parts:
                        if re.match(r'^Po\d+$', part):
                            po_name = part
                            members = get_po_members(conn, po_name)
                            if members:
                                portchannels[po_name] = members
                            break
            
            return portchannels
        except Exception as e:
            print(f"  ⚠️ Could not get port-channel information: {e}")
            return {}
    
    def audit_device(self, device_name: str, device_info: Dict[str, str]) -> Optional[DeviceState]:
        """Perform complete audit of a single device"""
        print(f"\n🔍 Auditing device: {device_name} ({device_info['host']})")
        
        username, password = self.credentials
        conn, _, _ = connect_with_fallback(device_info['host'], username, password)
        
        if not conn:
            print(f"❌ Failed to connect to {device_name}")
            return None
        
        try:
            # Get hostname
            hostname = conn.send_command("show running-config | include hostname", cmd_verify=False)
            hostname = hostname.split()[-1] if hostname.split() else device_name
            
            # Get all interfaces
            interfaces = self.get_device_ports(conn)
            print(f"  📊 Found {len(interfaces)} interfaces")
            
            # Get detailed config for each interface
            ports = {}
            for interface in interfaces:
                try:
                    ports[interface] = self.get_port_config(conn, interface)
                except Exception as e:
                    print(f"  ⚠️ Error getting config for {interface}: {e}")
                    continue
            
            # Get VLANs
            vlans = self.get_device_vlans(conn)
            print(f"  🏷️ Found {len(vlans)} VLANs")
            
            # Get port-channels
            portchannels = self.get_portchannels(conn)
            print(f"  🔗 Found {len(portchannels)} port-channels")
            
            device_state = DeviceState(
                hostname=hostname,
                ip_address=device_info['host'],
                device_type=device_info.get('device_type', 'cisco_ios'),
                timestamp=datetime.now().isoformat(),
                ports=ports,
                vlans=vlans,
                portchannels=portchannels
            )
            
            print(f"✅ Successfully audited {device_name}")
            return device_state
            
        except Exception as e:
            print(f"❌ Error auditing {device_name}: {e}")
            return None
        finally:
            conn.disconnect()
    
    def audit_all_devices(self) -> Dict[str, DeviceState]:
        """Audit all devices in the inventory"""
        print(f"🚀 Starting network audit of {len(self.devices)} devices...")
        
        results = {}
        for device_name, device_info in self.devices.items():
            state = self.audit_device(device_name, device_info)
            if state:
                results[device_name] = state
        
        print(f"\n📊 Audit completed: {len(results)}/{len(self.devices)} devices successful")
        return results
    
    def save_audit_results(self, results: Dict[str, DeviceState], output_file: str = None):
        """Save audit results to JSON file"""
        if not output_file:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = f"network_audit_{timestamp}.json"
        
        # Convert to serializable format
        serializable_results = {}
        for device_name, state in results.items():
            device_dict = asdict(state)
            # Convert PortConfig objects to dicts
            device_dict['ports'] = {k: asdict(v) for k, v in state.ports.items()}
            serializable_results[device_name] = device_dict
        
        output_path = Path(output_file)
        with open(output_path, 'w') as f:
            json.dump(serializable_results, f, indent=2)
        
        print(f"💾 Audit results saved to: {output_path.absolute()}")
        return str(output_path.absolute())
    
    def compare_audits(self, before_file: str, after_file: str) -> Dict[str, Any]:
        """Compare two audit files and report differences"""
        print(f"🔍 Comparing audits: {before_file} vs {after_file}")
        
        with open(before_file, 'r') as f:
            before_data = json.load(f)
        
        with open(after_file, 'r') as f:
            after_data = json.load(f)
        
        differences = {
            'added_devices': [],
            'removed_devices': [],
            'device_changes': {}
        }
        
        # Find added/removed devices
        before_devices = set(before_data.keys())
        after_devices = set(after_data.keys())
        
        differences['added_devices'] = list(after_devices - before_devices)
        differences['removed_devices'] = list(before_devices - after_devices)
        
        # Compare common devices
        common_devices = before_devices & after_devices
        
        for device in common_devices:
            device_changes = self._compare_device_states(
                before_data[device], 
                after_data[device]
            )
            if device_changes:
                differences['device_changes'][device] = device_changes
        
        return differences
    
    def _compare_device_states(self, before: Dict, after: Dict) -> Dict[str, Any]:
        """Compare states of a single device"""
        changes = {
            'port_changes': {},
            'vlan_changes': {},
            'general_changes': {}
        }
        
        # Compare timestamps
        if before.get('timestamp') != after.get('timestamp'):
            changes['general_changes']['timestamp'] = {
                'before': before.get('timestamp'),
                'after': after.get('timestamp')
            }
        
        # Compare ports
        before_ports = before.get('ports', {})
        after_ports = after.get('ports', {})
        
        all_ports = set(before_ports.keys()) | set(after_ports.keys())
        
        for port in all_ports:
            port_changes = {}
            
            if port not in before_ports:
                port_changes['status'] = 'added'
                port_changes['config'] = after_ports[port]
            elif port not in after_ports:
                port_changes['status'] = 'removed'
                port_changes['config'] = before_ports[port]
            else:
                # Compare port configurations
                before_config = before_ports[port]
                after_config = after_ports[port]
                
                for key in before_config:
                    if before_config[key] != after_config.get(key):
                        if 'config_changes' not in port_changes:
                            port_changes['config_changes'] = {}
                        port_changes['config_changes'][key] = {
                            'before': before_config[key],
                            'after': after_config.get(key)
                        }
            
            if port_changes:
                changes['port_changes'][port] = port_changes
        
        # Remove empty sections
        changes = {k: v for k, v in changes.items() if v}
        
        return changes
    
    def generate_report(self, audit_data: Dict[str, DeviceState], output_file: str = None):
        """Generate a human-readable report"""
        if not output_file:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = f"network_report_{timestamp}.md"
        
        with open(output_file, 'w') as f:
            f.write("# Network Audit Report\n\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            
            f.write(f"## Summary\n\n")
            f.write(f"- **Devices Audited**: {len(audit_data)}\n")
            
            total_ports = sum(len(device.ports) for device in audit_data.values())
            f.write(f"- **Total Ports**: {total_ports}\n")
            
            total_vlans = sum(len(device.vlans) for device in audit_data.values())
            f.write(f"- **Total VLANs**: {total_vlans}\n\n")
            
            for device_name, device_state in audit_data.items():
                f.write(f"## Device: {device_name}\n\n")
                f.write(f"- **Hostname**: {device_state.hostname}\n")
                f.write(f"- **IP Address**: {device_state.ip_address}\n")
                f.write(f"- **Device Type**: {device_state.device_type}\n")
                f.write(f"- **Audit Time**: {device_state.timestamp}\n")
                f.write(f"- **Ports**: {len(device_state.ports)}\n")
                f.write(f"- **VLANs**: {len(device_state.vlans)}\n")
                f.write(f"- **Port-Channels**: {len(device_state.portchannels)}\n\n")
                
                # Port summary
                if device_state.ports:
                    f.write(f"### Port Summary\n\n")
                    f.write("| Interface | Status | Mode | Access VLAN | Voice VLAN |\n")
                    f.write("|-----------|--------|------|-------------|------------|\n")
                    
                    for port_name, port_config in sorted(device_state.ports.items()):
                        f.write(f"| {port_config.interface} | {port_config.operational_status} | {port_config.mode} | {port_config.access_vlan} | {port_config.voice_vlan} |\n")
                    
                    f.write("\n")
        
        print(f"📄 Report generated: {output_file}")
        return output_file

def main():
    """Main function for command-line usage"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Network Audit Tool")
    parser.add_argument("--devices", default="inventory/devices.yml", 
                       help="Path to devices inventory file")
    parser.add_argument("--output", help="Output file for audit results")
    parser.add_argument("--report", action="store_true", 
                       help="Generate human-readable report")
    parser.add_argument("--compare", nargs=2, metavar=("BEFORE", "AFTER"),
                       help="Compare two audit files")
    
    args = parser.parse_args()
    
    if args.compare:
        auditor = NetworkAuditor(args.devices)
        differences = auditor.compare_audits(args.compare[0], args.compare[1])
        
        if any(differences.values()):
            print("\n📊 Changes detected:")
            print(json.dumps(differences, indent=2))
        else:
            print("\n✅ No changes detected between audits")
        return
    
    # Perform audit
    auditor = NetworkAuditor(args.devices)
    results = auditor.audit_all_devices()
    
    if not results:
        print("❌ No devices successfully audited")
        sys.exit(1)
    
    # Save results
    output_file = auditor.save_audit_results(results, args.output)
    
    # Generate report if requested
    if args.report:
        auditor.generate_report(results)
    
    print(f"\n✅ Audit completed successfully!")
    print(f"📁 Results: {output_file}")

if __name__ == "__main__":
    main()
