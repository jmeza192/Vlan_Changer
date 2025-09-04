#!/usr/bin/env python3
"""
Helper Functions for Network Testing and Validation

This module provides utility functions used across the testing framework
for network device validation, configuration checks, and reporting.
"""

import re
import json
import yaml
import logging
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path
from datetime import datetime

def load_device_inventory(file_path: str = "inventory/devices.yml") -> Dict[str, Dict[str, str]]:
    """Load device inventory from YAML file"""
    try:
        with open(file_path, 'r') as f:
            data = yaml.safe_load(f)
            return data.get('devices', {})
    except FileNotFoundError:
        logging.error(f"Device inventory file not found: {file_path}")
        raise
    except yaml.YAMLError as e:
        logging.error(f"Error parsing device inventory: {e}")
        raise

def load_test_targets(file_path: str = "inventory/targets.yml") -> Dict[str, Any]:
    """Load test targets configuration"""
    try:
        with open(file_path, 'r') as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        logging.error(f"Test targets file not found: {file_path}")
        raise
    except yaml.YAMLError as e:
        logging.error(f"Error parsing test targets: {e}")
        raise

def validate_vlan_id(vlan_id: str) -> bool:
    """Validate VLAN ID is in valid range"""
    try:
        vlan_num = int(vlan_id)
        return 1 <= vlan_num <= 4094
    except ValueError:
        return False

def validate_interface_name(interface: str) -> bool:
    """Validate interface name format"""
    # Common Cisco interface patterns
    patterns = [
        r'^GigabitEthernet\d+/\d+(/\d+)?$',  # GigabitEthernet0/1
        r'^FastEthernet\d+/\d+(/\d+)?$',     # FastEthernet0/1
        r'^TenGigabitEthernet\d+/\d+(/\d+)?$',  # TenGigabitEthernet0/1
        r'^Ethernet\d+/\d+(/\d+)?$',         # Ethernet0/1
        r'^Gi\d+/\d+(/\d+)?$',               # Gi0/1 (short form)
        r'^Fa\d+/\d+(/\d+)?$',               # Fa0/1 (short form)
        r'^Te\d+/\d+(/\d+)?$',               # Te0/1 (short form)
        r'^Et\d+/\d+(/\d+)?$',               # Et0/1 (short form)
    ]
    
    return any(re.match(pattern, interface, re.IGNORECASE) for pattern in patterns)

def normalize_interface_name(interface: str) -> str:
    """Normalize interface name to full format"""
    # Mapping of short forms to full forms
    expansions = {
        'Gi': 'GigabitEthernet',
        'Fa': 'FastEthernet', 
        'Te': 'TenGigabitEthernet',
        'Et': 'Ethernet'
    }
    
    for short, full in expansions.items():
        if interface.startswith(short):
            return interface.replace(short, full, 1)
    
    return interface

def parse_interface_config(config_text: str) -> Dict[str, str]:
    """Parse interface configuration text into structured data"""
    config = {
        'access_vlan': '1',
        'voice_vlan': 'none',
        'mode': 'access',
        'description': '',
        'speed': 'auto',
        'duplex': 'auto',
        'portfast': False,
        'shutdown': False
    }
    
    for line in config_text.splitlines():
        line = line.strip()
        
        if line.startswith('switchport access vlan '):
            config['access_vlan'] = line.split()[-1]
        elif line.startswith('switchport voice vlan '):
            config['voice_vlan'] = line.split()[-1]
        elif line.startswith('switchport mode '):
            config['mode'] = line.split()[-1]
        elif line.startswith('description '):
            config['description'] = line[12:]  # Remove 'description '
        elif line.startswith('speed '):
            config['speed'] = line.split()[-1]
        elif line.startswith('duplex '):
            config['duplex'] = line.split()[-1]
        elif 'spanning-tree portfast' in line:
            config['portfast'] = True
        elif line == 'shutdown':
            config['shutdown'] = True
    
    return config

def parse_switchport_output(output: str) -> Dict[str, str]:
    """Parse 'show interface switchport' output"""
    config = {
        'mode': 'unknown',
        'access_vlan': '1',
        'voice_vlan': 'none'
    }
    
    for line in output.splitlines():
        line = line.strip()
        
        if 'Administrative Mode:' in line:
            config['mode'] = line.split()[-1]
        elif 'Access Mode VLAN:' in line:
            config['access_vlan'] = line.split()[-1]
        elif 'Voice VLAN:' in line:
            config['voice_vlan'] = line.split()[-1]
    
    return config

def compare_port_configs(before: Dict[str, str], after: Dict[str, str]) -> Dict[str, Dict[str, str]]:
    """Compare two port configurations and return differences"""
    differences = {}
    
    # Check all keys from both configs
    all_keys = set(before.keys()) | set(after.keys())
    
    for key in all_keys:
        before_val = before.get(key, 'NOT_SET')
        after_val = after.get(key, 'NOT_SET')
        
        if before_val != after_val:
            differences[key] = {
                'before': before_val,
                'after': after_val
            }
    
    return differences

def validate_port_connectivity(conn, interface: str) -> Dict[str, Any]:
    """Validate port connectivity and status"""
    result = {
        'interface': interface,
        'operational_status': 'unknown',
        'admin_status': 'unknown',
        'link_status': 'unknown',
        'errors': [],
        'warnings': []
    }
    
    try:
        # Check interface status
        status_output = conn.send_command(
            f"show interface {interface} status",
            read_timeout=30,
            cmd_verify=False
        )
        
        # Parse status output
        for line in status_output.splitlines():
            if interface in line:
                parts = line.split()
                if len(parts) >= 3:
                    result['operational_status'] = parts[1] if len(parts) > 1 else 'unknown'
                    result['admin_status'] = parts[2] if len(parts) > 2 else 'unknown'
                break
        
        # Check for errors
        interface_output = conn.send_command(
            f"show interface {interface}",
            read_timeout=30,
            cmd_verify=False
        )
        
        if 'line protocol is down' in interface_output.lower():
            result['warnings'].append('Line protocol is down')
        
        # Look for error counters
        error_patterns = [
            (r'(\d+) input errors', 'input_errors'),
            (r'(\d+) output errors', 'output_errors'),
            (r'(\d+) CRC', 'crc_errors'),
            (r'(\d+) collisions', 'collisions')
        ]
        
        for pattern, error_type in error_patterns:
            match = re.search(pattern, interface_output)
            if match:
                error_count = int(match.group(1))
                if error_count > 0:
                    result['warnings'].append(f'{error_type}: {error_count}')
        
        result['link_status'] = 'up' if 'line protocol is up' in interface_output.lower() else 'down'
        
    except Exception as e:
        result['errors'].append(f'Error checking connectivity: {str(e)}')
    
    return result

def check_vlan_exists(conn, vlan_id: str) -> bool:
    """Check if VLAN exists on the device"""
    try:
        output = conn.send_command("show vlan brief", read_timeout=30, cmd_verify=False)
        
        for line in output.splitlines():
            line = line.strip()
            if line.startswith(vlan_id + ' '):
                return True
        
        return False
    except Exception:
        return False

def get_port_channel_members(conn, po_interface: str) -> List[str]:
    """Get member interfaces of a port-channel"""
    from VlanChange import get_po_members  # Import the existing function
    return get_po_members(conn, po_interface)

def validate_test_prerequisites(devices: Dict[str, Dict[str, str]], 
                              target_config: Dict[str, Any]) -> List[str]:
    """Validate that test prerequisites are met"""
    errors = []
    
    # Validate target device exists
    target_device = target_config.get('target', {}).get('device')
    if not target_device:
        errors.append("Target device not specified in configuration")
    elif target_device not in devices:
        errors.append(f"Target device '{target_device}' not found in device inventory")
    
    # Validate target interface format
    target_interface = target_config.get('target', {}).get('interface')
    if not target_interface:
        errors.append("Target interface not specified in configuration")
    elif not validate_interface_name(target_interface):
        errors.append(f"Invalid interface name format: '{target_interface}'")
    
    # Validate test VLAN
    test_vlan = str(target_config.get('test_vlan', ''))
    if not test_vlan:
        errors.append("Test VLAN not specified in configuration")
    elif not validate_vlan_id(test_vlan):
        errors.append(f"Invalid VLAN ID: '{test_vlan}' (must be 1-4094)")
    
    return errors

def format_test_summary(test_results: Dict[str, Any]) -> str:
    """Format test results into a readable summary"""
    summary = []
    
    summary.append("=" * 60)
    summary.append("NETWORK VLAN CHANGE TEST SUMMARY")
    summary.append("=" * 60)
    
    # Basic info
    summary.append(f"Test ID: {test_results.get('test_id', 'Unknown')}")
    summary.append(f"Start Time: {test_results.get('start_time', 'Unknown')}")
    summary.append(f"End Time: {test_results.get('end_time', 'Unknown')}")
    summary.append("")
    
    # Test configuration
    summary.append("Test Configuration:")
    summary.append(f"  Device: {test_results.get('target_device', 'Unknown')}")
    summary.append(f"  Interface: {test_results.get('target_interface', 'Unknown')}")
    summary.append(f"  Original VLAN: {test_results.get('original_vlan', 'Unknown')}")
    summary.append(f"  Target VLAN: {test_results.get('target_vlan', 'Unknown')}")
    summary.append("")
    
    # Results
    success = test_results.get('success', False)
    summary.append(f"Overall Result: {'✅ PASSED' if success else '❌ FAILED'}")
    summary.append("")
    
    # Detailed results
    summary.append("Detailed Results:")
    summary.append(f"  Changes Applied: {'✅ Yes' if test_results.get('changes_applied') else '❌ No'}")
    summary.append(f"  Rollback Performed: {'✅ Yes' if test_results.get('rollback_performed') else '❌ No'}")
    summary.append("")
    
    # Errors and warnings
    errors = test_results.get('errors', [])
    if errors:
        summary.append("Errors:")
        for error in errors:
            summary.append(f"  ❌ {error}")
        summary.append("")
    
    warnings = test_results.get('warnings', [])
    if warnings:
        summary.append("Warnings:")
        for warning in warnings:
            summary.append(f"  ⚠️ {warning}")
        summary.append("")
    
    summary.append("=" * 60)
    
    return '\n'.join(summary)

def create_test_report_json(test_results: Dict[str, Any], 
                           pre_audit: Dict = None, 
                           post_audit: Dict = None) -> Dict[str, Any]:
    """Create a comprehensive JSON test report"""
    report = {
        'metadata': {
            'report_type': 'network_vlan_test',
            'version': '1.0',
            'generated_at': datetime.now().isoformat(),
            'test_id': test_results.get('test_id')
        },
        'test_configuration': {
            'target_device': test_results.get('target_device'),
            'target_interface': test_results.get('target_interface'),
            'original_vlan': test_results.get('original_vlan'),
            'target_vlan': test_results.get('target_vlan')
        },
        'test_execution': {
            'start_time': test_results.get('start_time'),
            'end_time': test_results.get('end_time'),
            'success': test_results.get('success', False),
            'changes_applied': test_results.get('changes_applied', False),
            'rollback_performed': test_results.get('rollback_performed', False)
        },
        'issues': {
            'errors': test_results.get('errors', []),
            'warnings': test_results.get('warnings', [])
        }
    }
    
    # Add audit data if available
    if pre_audit:
        report['pre_change_audit'] = {
            'timestamp': datetime.now().isoformat(),
            'device_count': len(pre_audit),
            'devices': list(pre_audit.keys())
        }
    
    if post_audit:
        report['post_change_audit'] = {
            'timestamp': datetime.now().isoformat(),
            'device_count': len(post_audit),
            'devices': list(post_audit.keys())
        }
    
    return report

def save_json_report(report_data: Dict[str, Any], filename: str = None) -> str:
    """Save report data to JSON file"""
    if not filename:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"test_report_{timestamp}.json"
    
    with open(filename, 'w') as f:
        json.dump(report_data, f, indent=2, default=str)
    
    return filename

def log_test_step(step_name: str, success: bool, details: str = ""):
    """Log a test step with consistent formatting"""
    status = "✅ PASSED" if success else "❌ FAILED"
    message = f"[{step_name}] {status}"
    
    if details:
        message += f" - {details}"
    
    if success:
        logging.info(message)
    else:
        logging.error(message)
    
    return message
