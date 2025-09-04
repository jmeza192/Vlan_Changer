#!/usr/bin/env python3
"""
End-to-End VLAN Change Testing Framework

This module provides comprehensive testing for VLAN change operations in the CI/CD pipeline.
It validates that VLAN changes work correctly and don't have unintended side effects.

Test Flow:
1. Pre-test audit - Capture current network state
2. Execute VLAN change - Apply the target configuration
3. Post-test validation - Verify changes were applied correctly
4. Side-effect check - Ensure no other ports were affected
5. Cleanup/Rollback - Restore original state if needed

Key Safety Features:
- Comprehensive pre/post state comparison
- Automated rollback on failure
- Detailed logging and reporting
- Validation of all network devices
"""

import json
import yaml
import sys
import os
import time
import pytest
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime
import tempfile

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent))
from VlanChange import connect_with_fallback, push_config_with_retry
from tests.network_audit import NetworkAuditor, DeviceState, PortConfig

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('test_results.log'),
        logging.StreamHandler()
    ]
)

class VlanTestFramework:
    """Main framework for VLAN change testing"""
    
    def __init__(self, devices_file: str = "inventory/devices.yml", 
                 targets_file: str = "inventory/targets.yml"):
        """Initialize the test framework"""
        self.devices_file = Path(devices_file)
        self.targets_file = Path(targets_file)
        self.auditor = NetworkAuditor(str(self.devices_file))
        self.test_config = self._load_test_config()
        self.credentials = self._load_credentials()
        
        # Test state tracking
        self.pre_test_audit = None
        self.post_test_audit = None
        self.test_results = {
            'test_id': datetime.now().strftime("%Y%m%d_%H%M%S"),
            'start_time': None,
            'end_time': None,
            'target_device': None,
            'target_interface': None,
            'target_vlan': None,
            'original_vlan': None,
            'success': False,
            'changes_applied': False,
            'rollback_performed': False,
            'errors': [],
            'warnings': []
        }
    
    def _load_test_config(self) -> Dict[str, Any]:
        """Load test configuration from targets.yml"""
        try:
            with open(self.targets_file, 'r') as f:
                return yaml.safe_load(f)
        except FileNotFoundError:
            logging.error(f"Test config file not found: {self.targets_file}")
            sys.exit(1)
        except yaml.YAMLError as e:
            logging.error(f"Error parsing test config: {e}")
            sys.exit(1)
    
    def _load_credentials(self) -> Tuple[str, str]:
        """Load credentials from environment variables"""
        from dotenv import load_dotenv
        load_dotenv()
        
        username = os.getenv('PRIMARY_USERNAME')
        password = os.getenv('PRIMARY_PASSWORD')
        
        if not username or not password:
            logging.error("PRIMARY_USERNAME and PRIMARY_PASSWORD must be set")
            sys.exit(1)
            
        return username, password
    
    def validate_test_environment(self) -> bool:
        """Validate that test environment is ready"""
        logging.info("🔍 Validating test environment...")
        
        # Check if all required devices are accessible
        username, password = self.credentials
        failed_devices = []
        
        for device_name, device_info in self.auditor.devices.items():
            logging.info(f"  Testing connectivity to {device_name}...")
            conn, _, _ = connect_with_fallback(device_info['host'], username, password)
            
            if not conn:
                failed_devices.append(device_name)
                logging.error(f"  ❌ Cannot connect to {device_name}")
            else:
                logging.info(f"  ✅ Connected to {device_name}")
                conn.disconnect()
        
        if failed_devices:
            logging.error(f"❌ Cannot connect to devices: {', '.join(failed_devices)}")
            return False
        
        # Validate test target exists
        target_device = self.test_config.get('target', {}).get('device')
        target_interface = self.test_config.get('target', {}).get('interface')
        
        if not target_device or not target_interface:
            logging.error("❌ Target device and interface must be specified in targets.yml")
            return False
        
        if target_device not in self.auditor.devices:
            logging.error(f"❌ Target device '{target_device}' not found in inventory")
            return False
        
        logging.info("✅ Test environment validation passed")
        return True
    
    def perform_pre_test_audit(self) -> Dict[str, DeviceState]:
        """Capture network state before test"""
        logging.info("📋 Performing pre-test network audit...")
        
        self.test_results['start_time'] = datetime.now().isoformat()
        self.pre_test_audit = self.auditor.audit_all_devices()
        
        if not self.pre_test_audit:
            raise Exception("Failed to perform pre-test audit")
        
        # Save pre-test state
        audit_file = f"pre_test_audit_{self.test_results['test_id']}.json"
        self.auditor.save_audit_results(self.pre_test_audit, audit_file)
        
        logging.info(f"✅ Pre-test audit completed: {len(self.pre_test_audit)} devices")
        return self.pre_test_audit
    
    def get_current_port_config(self, device_name: str, interface: str) -> Optional[PortConfig]:
        """Get current configuration of target port"""
        if not self.pre_test_audit or device_name not in self.pre_test_audit:
            return None
        
        device_state = self.pre_test_audit[device_name]
        return device_state.ports.get(interface)
    
    def apply_vlan_change(self, device_name: str, interface: str, 
                         new_vlan: str, voice_vlan: str = None) -> bool:
        """Apply VLAN change to target interface"""
        logging.info(f"🔧 Applying VLAN change: {device_name}:{interface} -> VLAN {new_vlan}")
        
        self.test_results['target_device'] = device_name
        self.test_results['target_interface'] = interface
        self.test_results['target_vlan'] = new_vlan
        
        # Get current config for rollback
        current_config = self.get_current_port_config(device_name, interface)
        if current_config:
            self.test_results['original_vlan'] = current_config.access_vlan
            logging.info(f"  Original VLAN: {current_config.access_vlan}")
        
        # Connect to device
        device_info = self.auditor.devices[device_name]
        username, password = self.credentials
        conn, _, _ = connect_with_fallback(device_info['host'], username, password)
        
        if not conn:
            raise Exception(f"Failed to connect to {device_name}")
        
        try:
            # Prepare configuration commands
            commands = [
                f"default interface {interface}",
                f"interface {interface}",
                "switchport mode access",
                f"switchport access vlan {new_vlan}"
            ]
            
            if voice_vlan:
                commands.append(f"switchport voice vlan {voice_vlan}")
            
            commands.extend(["spanning-tree portfast", "no shutdown"])
            
            # Apply configuration
            success = push_config_with_retry(conn, commands)
            
            if success:
                self.test_results['changes_applied'] = True
                logging.info("✅ VLAN change applied successfully")
                return True
            else:
                raise Exception("Failed to apply VLAN configuration")
                
        except Exception as e:
            logging.error(f"❌ Error applying VLAN change: {e}")
            self.test_results['errors'].append(str(e))
            return False
        finally:
            conn.disconnect()
    
    def perform_post_test_audit(self) -> Dict[str, DeviceState]:
        """Capture network state after test"""
        logging.info("📋 Performing post-test network audit...")
        
        # Wait a moment for changes to propagate
        time.sleep(5)
        
        self.post_test_audit = self.auditor.audit_all_devices()
        
        if not self.post_test_audit:
            raise Exception("Failed to perform post-test audit")
        
        # Save post-test state
        audit_file = f"post_test_audit_{self.test_results['test_id']}.json"
        self.auditor.save_audit_results(self.post_test_audit, audit_file)
        
        logging.info(f"✅ Post-test audit completed: {len(self.post_test_audit)} devices")
        return self.post_test_audit
    
    def validate_vlan_change(self) -> bool:
        """Validate that VLAN change was applied correctly"""
        logging.info("🔍 Validating VLAN change...")
        
        if not self.pre_test_audit or not self.post_test_audit:
            logging.error("❌ Pre or post test audit data missing")
            return False
        
        target_device = self.test_results['target_device']
        target_interface = self.test_results['target_interface']
        expected_vlan = self.test_results['target_vlan']
        
        # Check if target device exists in both audits
        if target_device not in self.post_test_audit:
            logging.error(f"❌ Target device {target_device} not found in post-test audit")
            return False
        
        post_device = self.post_test_audit[target_device]
        
        # Check if target interface exists
        if target_interface not in post_device.ports:
            logging.error(f"❌ Target interface {target_interface} not found")
            return False
        
        post_config = post_device.ports[target_interface]
        
        # Validate VLAN assignment
        if post_config.access_vlan != expected_vlan:
            logging.error(f"❌ VLAN validation failed: expected {expected_vlan}, got {post_config.access_vlan}")
            return False
        
        # Validate port is operational
        if post_config.operational_status.lower() not in ['up', 'connected']:
            logging.warning(f"⚠️ Port {target_interface} operational status: {post_config.operational_status}")
            self.test_results['warnings'].append(f"Port operational status: {post_config.operational_status}")
        
        logging.info(f"✅ VLAN change validated: {target_interface} is in VLAN {expected_vlan}")
        return True
    
    def check_side_effects(self) -> bool:
        """Check that no other ports were unintentionally modified"""
        logging.info("🔍 Checking for unintended side effects...")
        
        if not self.pre_test_audit or not self.post_test_audit:
            logging.error("❌ Pre or post test audit data missing")
            return False
        
        target_device = self.test_results['target_device']
        target_interface = self.test_results['target_interface']
        
        side_effects_found = False
        
        # Check all devices for changes
        for device_name in self.pre_test_audit:
            if device_name not in self.post_test_audit:
                logging.warning(f"⚠️ Device {device_name} missing from post-test audit")
                continue
            
            pre_device = self.pre_test_audit[device_name]
            post_device = self.post_test_audit[device_name]
            
            # Check all ports on this device
            for interface in pre_device.ports:
                # Skip the target interface (expected to change)
                if device_name == target_device and interface == target_interface:
                    continue
                
                if interface not in post_device.ports:
                    logging.warning(f"⚠️ Interface {device_name}:{interface} missing from post-test")
                    continue
                
                pre_config = pre_device.ports[interface]
                post_config = post_device.ports[interface]
                
                # Check for VLAN changes
                if pre_config.access_vlan != post_config.access_vlan:
                    logging.error(f"❌ Unexpected VLAN change: {device_name}:{interface} "
                                f"VLAN {pre_config.access_vlan} -> {post_config.access_vlan}")
                    side_effects_found = True
                
                # Check for mode changes
                if pre_config.mode != post_config.mode:
                    logging.warning(f"⚠️ Mode change: {device_name}:{interface} "
                                  f"{pre_config.mode} -> {post_config.mode}")
                    self.test_results['warnings'].append(
                        f"Mode change on {device_name}:{interface}: {pre_config.mode} -> {post_config.mode}"
                    )
        
        if side_effects_found:
            logging.error("❌ Side effects detected!")
            return False
        else:
            logging.info("✅ No unintended side effects detected")
            return True
    
    def rollback_changes(self) -> bool:
        """Rollback changes to original state"""
        logging.info("🔄 Performing rollback...")
        
        target_device = self.test_results['target_device']
        target_interface = self.test_results['target_interface']
        original_vlan = self.test_results['original_vlan']
        
        if not original_vlan:
            logging.error("❌ Original VLAN not recorded, cannot rollback")
            return False
        
        try:
            success = self.apply_vlan_change(target_device, target_interface, original_vlan)
            if success:
                self.test_results['rollback_performed'] = True
                logging.info(f"✅ Rollback completed: {target_interface} -> VLAN {original_vlan}")
                return True
            else:
                logging.error("❌ Rollback failed")
                return False
        except Exception as e:
            logging.error(f"❌ Rollback error: {e}")
            return False
    
    def generate_test_report(self) -> str:
        """Generate comprehensive test report"""
        self.test_results['end_time'] = datetime.now().isoformat()
        
        report_file = f"test_report_{self.test_results['test_id']}.md"
        
        with open(report_file, 'w') as f:
            f.write("# VLAN Change Test Report\n\n")
            f.write(f"**Test ID**: {self.test_results['test_id']}\n")
            f.write(f"**Start Time**: {self.test_results['start_time']}\n")
            f.write(f"**End Time**: {self.test_results['end_time']}\n")
            f.write(f"**Success**: {'✅ PASSED' if self.test_results['success'] else '❌ FAILED'}\n\n")
            
            f.write("## Test Configuration\n\n")
            f.write(f"- **Target Device**: {self.test_results['target_device']}\n")
            f.write(f"- **Target Interface**: {self.test_results['target_interface']}\n")
            f.write(f"- **Original VLAN**: {self.test_results['original_vlan']}\n")
            f.write(f"- **Target VLAN**: {self.test_results['target_vlan']}\n\n")
            
            f.write("## Test Results\n\n")
            f.write(f"- **Changes Applied**: {'✅ Yes' if self.test_results['changes_applied'] else '❌ No'}\n")
            f.write(f"- **Rollback Performed**: {'✅ Yes' if self.test_results['rollback_performed'] else '❌ No'}\n\n")
            
            if self.test_results['errors']:
                f.write("## Errors\n\n")
                for error in self.test_results['errors']:
                    f.write(f"- ❌ {error}\n")
                f.write("\n")
            
            if self.test_results['warnings']:
                f.write("## Warnings\n\n")
                for warning in self.test_results['warnings']:
                    f.write(f"- ⚠️ {warning}\n")
                f.write("\n")
            
            # Add comparison summary if available
            if self.pre_test_audit and self.post_test_audit:
                f.write("## Detailed Comparison\n\n")
                
                # Save temporary files for comparison
                with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as before_file:
                    self.auditor.save_audit_results(self.pre_test_audit, before_file.name)
                    before_path = before_file.name
                
                with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as after_file:
                    self.auditor.save_audit_results(self.post_test_audit, after_file.name)
                    after_path = after_file.name
                
                try:
                    differences = self.auditor.compare_audits(before_path, after_path)
                    
                    if differences.get('device_changes'):
                        for device, changes in differences['device_changes'].items():
                            f.write(f"### {device}\n\n")
                            
                            if changes.get('port_changes'):
                                f.write("#### Port Changes\n\n")
                                for port, port_changes in changes['port_changes'].items():
                                    f.write(f"**{port}**:\n")
                                    if 'config_changes' in port_changes:
                                        for config_key, change in port_changes['config_changes'].items():
                                            f.write(f"- {config_key}: {change['before']} → {change['after']}\n")
                                    f.write("\n")
                    else:
                        f.write("No device changes detected.\n\n")
                        
                finally:
                    # Cleanup temporary files
                    os.unlink(before_path)
                    os.unlink(after_path)
        
        logging.info(f"📄 Test report generated: {report_file}")
        return report_file
    
    def run_full_test(self, cleanup: bool = True) -> bool:
        """Run the complete end-to-end test"""
        logging.info("🚀 Starting end-to-end VLAN change test...")
        
        try:
            # 1. Validate environment
            if not self.validate_test_environment():
                return False
            
            # 2. Pre-test audit
            self.perform_pre_test_audit()
            
            # 3. Apply VLAN change
            target_device = self.test_config['target']['device']
            target_interface = self.test_config['target']['interface']
            target_vlan = str(self.test_config['test_vlan'])
            
            if not self.apply_vlan_change(target_device, target_interface, target_vlan):
                return False
            
            # 4. Post-test audit
            self.perform_post_test_audit()
            
            # 5. Validate change
            if not self.validate_vlan_change():
                return False
            
            # 6. Check side effects
            if not self.check_side_effects():
                return False
            
            # 7. Cleanup/Rollback
            if cleanup:
                if not self.rollback_changes():
                    logging.warning("⚠️ Rollback failed, but test otherwise succeeded")
            
            self.test_results['success'] = True
            logging.info("✅ End-to-end test completed successfully!")
            return True
            
        except Exception as e:
            logging.error(f"❌ Test failed: {e}")
            self.test_results['errors'].append(str(e))
            
            # Attempt rollback on failure
            if cleanup and self.test_results['changes_applied']:
                logging.info("Attempting rollback due to test failure...")
                self.rollback_changes()
            
            return False
        
        finally:
            # Always generate report
            self.generate_test_report()

# Pytest fixtures and test functions
@pytest.fixture
def vlan_test_framework():
    """Pytest fixture to provide test framework"""
    return VlanTestFramework()

def test_environment_connectivity(vlan_test_framework):
    """Test that all devices are accessible"""
    assert vlan_test_framework.validate_test_environment(), "Environment validation failed"

def test_vlan_change_e2e(vlan_test_framework):
    """Run complete end-to-end VLAN change test"""
    assert vlan_test_framework.run_full_test(), "End-to-end test failed"

def test_vlan_change_no_cleanup(vlan_test_framework):
    """Run VLAN change test without cleanup (for manual verification)"""
    assert vlan_test_framework.run_full_test(cleanup=False), "Test failed"

# Command-line interface
def main():
    """Main function for command-line usage"""
    import argparse
    
    parser = argparse.ArgumentParser(description="VLAN Change E2E Test Framework")
    parser.add_argument("--devices", default="inventory/devices.yml",
                       help="Path to devices inventory file")
    parser.add_argument("--targets", default="inventory/targets.yml",
                       help="Path to test targets file")
    parser.add_argument("--no-cleanup", action="store_true",
                       help="Don't rollback changes after test")
    parser.add_argument("--validate-only", action="store_true",
                       help="Only validate environment connectivity")
    
    args = parser.parse_args()
    
    # Initialize framework
    framework = VlanTestFramework(args.devices, args.targets)
    
    if args.validate_only:
        success = framework.validate_test_environment()
        sys.exit(0 if success else 1)
    
    # Run full test
    success = framework.run_full_test(cleanup=not args.no_cleanup)
    
    print(f"\n{'='*50}")
    print(f"Test Result: {'✅ PASSED' if success else '❌ FAILED'}")
    print(f"{'='*50}")
    
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
