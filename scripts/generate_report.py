#!/usr/bin/env python3
"""
Comprehensive Report Generator for Network CI/CD Pipeline

This script generates detailed reports from test artifacts and audit data,
providing comprehensive analysis of network changes and their impacts.
"""

import json
import os
import sys
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional
import yaml

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent))
from tests.helpers import format_test_summary, create_test_report_json

class NetworkReportGenerator:
    """Generate comprehensive reports from test artifacts"""
    
    def __init__(self, artifacts_dir: str = "."):
        """Initialize report generator with artifacts directory"""
        self.artifacts_dir = Path(artifacts_dir)
        self.report_data = {
            'metadata': {
                'generated_at': datetime.now().isoformat(),
                'generator_version': '1.0',
                'artifacts_directory': str(self.artifacts_dir.absolute())
            },
            'summary': {},
            'details': {},
            'artifacts': []
        }
    
    def discover_artifacts(self) -> Dict[str, List[Path]]:
        """Discover and categorize test artifacts"""
        artifacts = {
            'pre_audits': [],
            'post_audits': [],
            'test_reports': [],
            'test_logs': [],
            'comparison_reports': [],
            'other': []
        }
        
        # Search for artifacts
        for file_path in self.artifacts_dir.rglob('*'):
            if file_path.is_file():
                name = file_path.name.lower()
                
                if 'pre_change_audit' in name or 'pre_test_audit' in name:
                    artifacts['pre_audits'].append(file_path)
                elif 'post_change_audit' in name or 'post_test_audit' in name:
                    artifacts['post_audits'].append(file_path)
                elif 'test_report' in name:
                    artifacts['test_reports'].append(file_path)
                elif 'test_results.log' in name:
                    artifacts['test_logs'].append(file_path)
                elif 'comparison_report' in name:
                    artifacts['comparison_reports'].append(file_path)
                else:
                    artifacts['other'].append(file_path)
        
        # Store in report data
        self.report_data['artifacts'] = {
            category: [str(f) for f in files] 
            for category, files in artifacts.items()
        }
        
        return artifacts
    
    def analyze_test_results(self, artifacts: Dict[str, List[Path]]) -> Dict[str, Any]:
        """Analyze test results from artifacts"""
        analysis = {
            'test_count': len(artifacts['test_reports']),
            'tests_passed': 0,
            'tests_failed': 0,
            'tests_with_warnings': 0,
            'devices_tested': set(),
            'interfaces_tested': set(),
            'vlans_tested': set(),
            'common_issues': [],
            'test_duration_stats': {}
        }
        
        test_durations = []
        all_errors = []
        all_warnings = []
        
        # Analyze each test report
        for report_file in artifacts['test_reports']:
            try:
                if report_file.suffix == '.json':
                    with open(report_file, 'r') as f:
                        test_data = json.load(f)
                    
                    # Extract test results
                    success = test_data.get('test_execution', {}).get('success', False)
                    if success:
                        analysis['tests_passed'] += 1
                    else:
                        analysis['tests_failed'] += 1
                    
                    # Track devices and interfaces tested
                    config = test_data.get('test_configuration', {})
                    if config.get('target_device'):
                        analysis['devices_tested'].add(config['target_device'])
                    if config.get('target_interface'):
                        analysis['interfaces_tested'].add(config['target_interface'])
                    if config.get('target_vlan'):
                        analysis['vlans_tested'].add(str(config['target_vlan']))
                    
                    # Collect errors and warnings
                    issues = test_data.get('issues', {})
                    all_errors.extend(issues.get('errors', []))
                    all_warnings.extend(issues.get('warnings', []))
                    
                    if issues.get('warnings'):
                        analysis['tests_with_warnings'] += 1
                    
                    # Calculate test duration
                    execution = test_data.get('test_execution', {})
                    start_time = execution.get('start_time')
                    end_time = execution.get('end_time')
                    
                    if start_time and end_time:
                        try:
                            start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                            end_dt = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
                            duration = (end_dt - start_dt).total_seconds()
                            test_durations.append(duration)
                        except ValueError:
                            pass
                
                elif report_file.suffix == '.md':
                    # Parse markdown reports for basic info
                    with open(report_file, 'r') as f:
                        content = f.read()
                    
                    if '✅ PASSED' in content:
                        analysis['tests_passed'] += 1
                    elif '❌ FAILED' in content:
                        analysis['tests_failed'] += 1
                        
            except Exception as e:
                print(f"Error analyzing {report_file}: {e}")
                continue
        
        # Convert sets to lists for JSON serialization
        analysis['devices_tested'] = list(analysis['devices_tested'])
        analysis['interfaces_tested'] = list(analysis['interfaces_tested'])
        analysis['vlans_tested'] = list(analysis['vlans_tested'])
        
        # Analyze common issues
        analysis['common_issues'] = self._find_common_issues(all_errors + all_warnings)
        
        # Calculate duration statistics
        if test_durations:
            analysis['test_duration_stats'] = {
                'average_seconds': sum(test_durations) / len(test_durations),
                'min_seconds': min(test_durations),
                'max_seconds': max(test_durations),
                'total_tests': len(test_durations)
            }
        
        return analysis
    
    def _find_common_issues(self, all_issues: List[str]) -> List[Dict[str, Any]]:
        """Find and categorize common issues"""
        issue_counts = {}
        
        for issue in all_issues:
            # Normalize issue text for grouping
            normalized = issue.lower().strip()
            if normalized in issue_counts:
                issue_counts[normalized] += 1
            else:
                issue_counts[normalized] = 1
        
        # Sort by frequency and return top issues
        common_issues = []
        for issue, count in sorted(issue_counts.items(), key=lambda x: x[1], reverse=True):
            if count > 1:  # Only include issues that occurred multiple times
                common_issues.append({
                    'issue': issue,
                    'count': count,
                    'category': self._categorize_issue(issue)
                })
        
        return common_issues[:10]  # Top 10 most common issues
    
    def _categorize_issue(self, issue: str) -> str:
        """Categorize an issue based on its text"""
        issue_lower = issue.lower()
        
        if any(word in issue_lower for word in ['connect', 'timeout', 'ssh']):
            return 'connectivity'
        elif any(word in issue_lower for word in ['vlan', 'switchport']):
            return 'configuration'
        elif any(word in issue_lower for word in ['interface', 'port']):
            return 'interface'
        elif any(word in issue_lower for word in ['auth', 'credential', 'login']):
            return 'authentication'
        else:
            return 'other'
    
    def analyze_network_coverage(self, artifacts: Dict[str, List[Path]]) -> Dict[str, Any]:
        """Analyze network coverage from audit data"""
        coverage = {
            'total_devices_audited': 0,
            'total_interfaces_audited': 0,
            'device_coverage': {},
            'vlan_distribution': {},
            'interface_types': {},
            'port_utilization': {}
        }
        
        # Analyze audit files
        for audit_file in artifacts['pre_audits'] + artifacts['post_audits']:
            try:
                with open(audit_file, 'r') as f:
                    audit_data = json.load(f)
                
                for device_name, device_data in audit_data.items():
                    if device_name not in coverage['device_coverage']:
                        coverage['device_coverage'][device_name] = {
                            'interfaces': 0,
                            'vlans_used': set(),
                            'interface_types': {}
                        }
                    
                    device_info = coverage['device_coverage'][device_name]
                    ports = device_data.get('ports', {})
                    
                    device_info['interfaces'] = len(ports)
                    coverage['total_interfaces_audited'] += len(ports)
                    
                    # Analyze each port
                    for interface_name, port_config in ports.items():
                        # Track VLAN usage
                        access_vlan = port_config.get('access_vlan', '1')
                        device_info['vlans_used'].add(access_vlan)
                        
                        if access_vlan not in coverage['vlan_distribution']:
                            coverage['vlan_distribution'][access_vlan] = 0
                        coverage['vlan_distribution'][access_vlan] += 1
                        
                        # Track interface types
                        interface_type = self._get_interface_type(interface_name)
                        if interface_type not in device_info['interface_types']:
                            device_info['interface_types'][interface_type] = 0
                        device_info['interface_types'][interface_type] += 1
                        
                        if interface_type not in coverage['interface_types']:
                            coverage['interface_types'][interface_type] = 0
                        coverage['interface_types'][interface_type] += 1
                        
                        # Track port utilization
                        status = port_config.get('operational_status', 'unknown').lower()
                        if status not in coverage['port_utilization']:
                            coverage['port_utilization'][status] = 0
                        coverage['port_utilization'][status] += 1
                
                coverage['total_devices_audited'] = len(coverage['device_coverage'])
                
            except Exception as e:
                print(f"Error analyzing audit file {audit_file}: {e}")
                continue
        
        # Convert sets to lists for JSON serialization
        for device_name, device_info in coverage['device_coverage'].items():
            device_info['vlans_used'] = list(device_info['vlans_used'])
        
        return coverage
    
    def _get_interface_type(self, interface_name: str) -> str:
        """Extract interface type from interface name"""
        interface_lower = interface_name.lower()
        
        if interface_lower.startswith(('gigabitethernet', 'gi')):
            return 'GigabitEthernet'
        elif interface_lower.startswith(('fastethernet', 'fa')):
            return 'FastEthernet'
        elif interface_lower.startswith(('tengigabitethernet', 'te')):
            return 'TenGigabitEthernet'
        elif interface_lower.startswith(('ethernet', 'et')):
            return 'Ethernet'
        elif interface_lower.startswith('po'):
            return 'PortChannel'
        else:
            return 'Other'
    
    def generate_executive_summary(self) -> str:
        """Generate executive summary of CI/CD pipeline results"""
        summary_lines = []
        
        # Overall status
        test_analysis = self.report_data.get('details', {}).get('test_analysis', {})
        total_tests = test_analysis.get('test_count', 0)
        passed_tests = test_analysis.get('tests_passed', 0)
        failed_tests = test_analysis.get('tests_failed', 0)
        
        if total_tests > 0:
            success_rate = (passed_tests / total_tests) * 100
            summary_lines.append(f"## Executive Summary")
            summary_lines.append(f"")
            summary_lines.append(f"**Overall Success Rate**: {success_rate:.1f}% ({passed_tests}/{total_tests} tests passed)")
            
            if success_rate >= 95:
                summary_lines.append(f"**Status**: ✅ Excellent - Pipeline performing very well")
            elif success_rate >= 80:
                summary_lines.append(f"**Status**: ⚠️ Good - Minor issues detected")
            elif success_rate >= 60:
                summary_lines.append(f"**Status**: ⚠️ Concerning - Multiple failures detected")
            else:
                summary_lines.append(f"**Status**: ❌ Critical - Pipeline needs immediate attention")
        else:
            summary_lines.append(f"**Status**: ⚠️ No test data available")
        
        # Network coverage
        coverage = self.report_data.get('details', {}).get('network_coverage', {})
        total_devices = coverage.get('total_devices_audited', 0)
        total_interfaces = coverage.get('total_interfaces_audited', 0)
        
        summary_lines.append(f"")
        summary_lines.append(f"**Network Coverage**:")
        summary_lines.append(f"- Devices Audited: {total_devices}")
        summary_lines.append(f"- Interfaces Monitored: {total_interfaces}")
        
        # Common issues
        common_issues = test_analysis.get('common_issues', [])
        if common_issues:
            summary_lines.append(f"")
            summary_lines.append(f"**Top Issues**:")
            for issue in common_issues[:3]:
                summary_lines.append(f"- {issue['issue']} (occurred {issue['count']} times)")
        
        return '\n'.join(summary_lines)
    
    def generate_detailed_report(self, output_file: str = None) -> str:
        """Generate comprehensive detailed report"""
        if not output_file:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = f"network_cicd_report_{timestamp}.md"
        
        # Discover and analyze artifacts
        artifacts = self.discover_artifacts()
        test_analysis = self.analyze_test_results(artifacts)
        network_coverage = self.analyze_network_coverage(artifacts)
        
        # Store analysis in report data
        self.report_data['details'] = {
            'test_analysis': test_analysis,
            'network_coverage': network_coverage
        }
        
        # Generate markdown report
        report_lines = []
        
        # Header
        report_lines.append("# 🔬 Network CI/CD Pipeline Report")
        report_lines.append("")
        report_lines.append(f"**Generated**: {self.report_data['metadata']['generated_at']}")
        report_lines.append(f"**Artifacts Directory**: `{self.report_data['metadata']['artifacts_directory']}`")
        report_lines.append("")
        
        # Executive Summary
        report_lines.append(self.generate_executive_summary())
        report_lines.append("")
        
        # Test Results Analysis
        report_lines.append("## 📊 Test Results Analysis")
        report_lines.append("")
        report_lines.append(f"| Metric | Value |")
        report_lines.append(f"|--------|-------|")
        report_lines.append(f"| Total Tests | {test_analysis['test_count']} |")
        report_lines.append(f"| Tests Passed | {test_analysis['tests_passed']} |")
        report_lines.append(f"| Tests Failed | {test_analysis['tests_failed']} |")
        report_lines.append(f"| Tests with Warnings | {test_analysis['tests_with_warnings']} |")
        report_lines.append(f"| Devices Tested | {len(test_analysis['devices_tested'])} |")
        report_lines.append(f"| Interfaces Tested | {len(test_analysis['interfaces_tested'])} |")
        report_lines.append(f"| VLANs Tested | {len(test_analysis['vlans_tested'])} |")
        report_lines.append("")
        
        # Test Duration Stats
        duration_stats = test_analysis.get('test_duration_stats', {})
        if duration_stats:
            report_lines.append("### ⏱️ Test Duration Statistics")
            report_lines.append("")
            report_lines.append(f"- **Average Duration**: {duration_stats.get('average_seconds', 0):.1f} seconds")
            report_lines.append(f"- **Minimum Duration**: {duration_stats.get('min_seconds', 0):.1f} seconds")
            report_lines.append(f"- **Maximum Duration**: {duration_stats.get('max_seconds', 0):.1f} seconds")
            report_lines.append("")
        
        # Network Coverage
        report_lines.append("## 🌐 Network Coverage Analysis")
        report_lines.append("")
        report_lines.append(f"**Total Devices Audited**: {network_coverage['total_devices_audited']}")
        report_lines.append(f"**Total Interfaces Monitored**: {network_coverage['total_interfaces_audited']}")
        report_lines.append("")
        
        # Device breakdown
        if network_coverage['device_coverage']:
            report_lines.append("### 📱 Device Breakdown")
            report_lines.append("")
            report_lines.append("| Device | Interfaces | VLANs Used | Interface Types |")
            report_lines.append("|--------|------------|------------|-----------------|")
            
            for device_name, device_info in network_coverage['device_coverage'].items():
                vlans = ', '.join(device_info['vlans_used'][:5])  # Show first 5 VLANs
                if len(device_info['vlans_used']) > 5:
                    vlans += f", ... (+{len(device_info['vlans_used']) - 5} more)"
                
                interface_types = ', '.join([
                    f"{itype}({count})" 
                    for itype, count in device_info['interface_types'].items()
                ])
                
                report_lines.append(f"| {device_name} | {device_info['interfaces']} | {vlans} | {interface_types} |")
            
            report_lines.append("")
        
        # VLAN Distribution
        vlan_dist = network_coverage.get('vlan_distribution', {})
        if vlan_dist:
            report_lines.append("### 🏷️ VLAN Usage Distribution")
            report_lines.append("")
            
            # Sort VLANs by usage count
            sorted_vlans = sorted(vlan_dist.items(), key=lambda x: x[1], reverse=True)
            
            report_lines.append("| VLAN | Port Count | Percentage |")
            report_lines.append("|------|------------|------------|")
            
            total_ports = sum(vlan_dist.values())
            for vlan, count in sorted_vlans[:10]:  # Top 10 VLANs
                percentage = (count / total_ports) * 100 if total_ports > 0 else 0
                report_lines.append(f"| {vlan} | {count} | {percentage:.1f}% |")
            
            report_lines.append("")
        
        # Common Issues
        common_issues = test_analysis.get('common_issues', [])
        if common_issues:
            report_lines.append("## ⚠️ Common Issues Analysis")
            report_lines.append("")
            
            # Group by category
            categories = {}
            for issue in common_issues:
                category = issue['category']
                if category not in categories:
                    categories[category] = []
                categories[category].append(issue)
            
            for category, issues in categories.items():
                report_lines.append(f"### {category.title()} Issues")
                report_lines.append("")
                
                for issue in issues:
                    report_lines.append(f"- **{issue['issue']}** (occurred {issue['count']} times)")
                
                report_lines.append("")
        
        # Artifacts Summary
        report_lines.append("## 📁 Artifacts Summary")
        report_lines.append("")
        
        artifact_categories = self.report_data.get('artifacts', {})
        for category, files in artifact_categories.items():
            if files:
                report_lines.append(f"### {category.replace('_', ' ').title()}")
                report_lines.append("")
                for file_path in files:
                    report_lines.append(f"- `{file_path}`")
                report_lines.append("")
        
        # Recommendations
        report_lines.append("## 💡 Recommendations")
        report_lines.append("")
        
        if test_analysis['tests_failed'] > 0:
            report_lines.append("- **High Priority**: Investigate and resolve test failures")
        
        if test_analysis['tests_with_warnings'] > 0:
            report_lines.append("- **Medium Priority**: Review and address test warnings")
        
        if common_issues:
            report_lines.append("- **Ongoing**: Address recurring issues identified in analysis")
        
        report_lines.append("- **Monitoring**: Continue regular CI/CD pipeline execution")
        report_lines.append("- **Documentation**: Keep network documentation updated")
        report_lines.append("")
        
        # Footer
        report_lines.append("---")
        report_lines.append(f"*Report generated by Network CI/CD Report Generator v{self.report_data['metadata']['generator_version']}*")
        
        # Write report to file
        report_content = '\n'.join(report_lines)
        with open(output_file, 'w') as f:
            f.write(report_content)
        
        print(f"📄 Detailed report generated: {output_file}")
        return output_file
    
    def generate_json_report(self, output_file: str = None) -> str:
        """Generate machine-readable JSON report"""
        if not output_file:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = f"network_cicd_report_{timestamp}.json"
        
        # Ensure we have all analysis data
        if 'details' not in self.report_data:
            artifacts = self.discover_artifacts()
            test_analysis = self.analyze_test_results(artifacts)
            network_coverage = self.analyze_network_coverage(artifacts)
            
            self.report_data['details'] = {
                'test_analysis': test_analysis,
                'network_coverage': network_coverage
            }
        
        # Write JSON report
        with open(output_file, 'w') as f:
            json.dump(self.report_data, f, indent=2, default=str)
        
        print(f"📄 JSON report generated: {output_file}")
        return output_file

def main():
    """Main function for command-line usage"""
    parser = argparse.ArgumentParser(description="Network CI/CD Report Generator")
    parser.add_argument("--artifacts-dir", default=".", 
                       help="Directory containing test artifacts")
    parser.add_argument("--output-md", help="Output markdown report file")
    parser.add_argument("--output-json", help="Output JSON report file")
    parser.add_argument("--summary-only", action="store_true",
                       help="Generate only executive summary")
    
    args = parser.parse_args()
    
    # Initialize report generator
    generator = NetworkReportGenerator(args.artifacts_dir)
    
    if args.summary_only:
        # Generate just the executive summary
        artifacts = generator.discover_artifacts()
        test_analysis = generator.analyze_test_results(artifacts)
        network_coverage = generator.analyze_network_coverage(artifacts)
        
        generator.report_data['details'] = {
            'test_analysis': test_analysis,
            'network_coverage': network_coverage
        }
        
        summary = generator.generate_executive_summary()
        print(summary)
    else:
        # Generate full reports
        md_file = generator.generate_detailed_report(args.output_md)
        json_file = generator.generate_json_report(args.output_json)
        
        print(f"\n📊 Report Generation Complete:")
        print(f"  📄 Markdown Report: {md_file}")
        print(f"  📄 JSON Report: {json_file}")

if __name__ == "__main__":
    main()
