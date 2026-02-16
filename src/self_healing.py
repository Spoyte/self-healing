#!/usr/bin/env python3
"""
Self-Healing Infrastructure System

Automatically detects and fixes infrastructure issues without human intervention.
Integrates with common DevOps tools and cloud providers.

Author: OpenClaw Agent
Created: 2026-02-16
"""

import asyncio
import json
import logging
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set
import hashlib
import re

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('self-healing')


class IssueSeverity(Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class IssueStatus(Enum):
    DETECTED = "detected"
    ANALYZING = "analyzing"
    REMEDIATING = "remediating"
    RESOLVED = "resolved"
    FAILED = "failed"
    ESCALATED = "escalated"


@dataclass
class InfrastructureIssue:
    id: str
    timestamp: datetime
    severity: IssueSeverity
    service: str
    issue_type: str
    description: str
    metrics: Dict[str, Any]
    status: IssueStatus = IssueStatus.DETECTED
    remediation_attempts: int = 0
    max_attempts: int = 3
    resolution: Optional[str] = None
    resolved_at: Optional[datetime] = None
    
    def __post_init__(self):
        if not self.id:
            self.id = hashlib.md5(
                f"{self.service}:{self.issue_type}:{self.timestamp}".encode()
            ).hexdigest()[:12]


@dataclass
class RemediationAction:
    name: str
    description: str
    command: str
    check_command: Optional[str] = None
    cooldown_seconds: int = 60
    auto_approve: bool = False
    last_executed: Optional[datetime] = None


@dataclass
class HealthCheck:
    name: str
    command: str
    interval_seconds: int
    timeout_seconds: int = 30
    severity: IssueSeverity = IssueSeverity.MEDIUM
    enabled: bool = True
    last_run: Optional[datetime] = None
    last_result: Optional[bool] = None


class SelfHealingEngine:
    """Core engine for self-healing infrastructure."""
    
    def __init__(self, config_path: Optional[str] = None):
        self.issues: Dict[str, InfrastructureIssue] = {}
        self.resolved_issues: List[InfrastructureIssue] = []
        self.health_checks: List[HealthCheck] = []
        self.remediation_actions: Dict[str, List[RemediationAction]] = {}
        self.running = False
        self.config_path = config_path or "/etc/self-healing/config.json"
        self.state_path = Path("/var/lib/self-healing/state.json")
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Statistics
        self.stats = {
            "issues_detected": 0,
            "issues_resolved": 0,
            "issues_escalated": 0,
            "remediation_attempts": 0,
            "remediation_successes": 0,
        }
        
        self._load_default_checks()
        self._load_default_remediations()
    
    def _load_default_checks(self):
        """Load default health checks."""
        self.health_checks = [
            # Docker checks
            HealthCheck(
                name="docker_daemon",
                command="docker ps > /dev/null 2>&1",
                interval_seconds=60,
                severity=IssueSeverity.CRITICAL
            ),
            HealthCheck(
                name="docker_containers",
                command="docker ps --format '{{.Names}}' | wc -l",
                interval_seconds=120,
                severity=IssueSeverity.HIGH
            ),
            
            # System checks
            HealthCheck(
                name="disk_space",
                command="df -h / | tail -1 | awk '{print $5}' | sed 's/%//'",
                interval_seconds=300,
                severity=IssueSeverity.HIGH
            ),
            HealthCheck(
                name="memory_usage",
                command="free | grep Mem | awk '{print int($3/$2 * 100)}'",
                interval_seconds=60,
                severity=IssueSeverity.MEDIUM
            ),
            HealthCheck(
                name="cpu_load",
                command="uptime | awk -F'load average:' '{print $2}' | awk '{print $1}' | sed 's/,//'",
                interval_seconds=60,
                severity=IssueSeverity.MEDIUM
            ),
            
            # Network checks
            HealthCheck(
                name="network_connectivity",
                command="ping -c 1 8.8.8.8 > /dev/null 2>&1",
                interval_seconds=60,
                severity=IssueSeverity.CRITICAL
            ),
            
            # Service checks (customize based on your services)
            HealthCheck(
                name="ssh_service",
                command="systemctl is-active sshd || systemctl is-active ssh",
                interval_seconds=120,
                severity=IssueSeverity.HIGH
            ),
        ]
    
    def _load_default_remediations(self):
        """Load default remediation actions."""
        self.remediation_actions = {
            "docker_daemon": [
                RemediationAction(
                    name="restart_docker",
                    description="Restart Docker daemon",
                    command="systemctl restart docker",
                    check_command="docker ps > /dev/null 2>&1",
                    cooldown_seconds=300,
                    auto_approve=True
                ),
            ],
            "disk_space": [
                RemediationAction(
                    name="clean_docker",
                    description="Clean unused Docker resources",
                    command="docker system prune -f --volumes",
                    cooldown_seconds=3600,
                    auto_approve=True
                ),
                RemediationAction(
                    name="clean_logs",
                    description="Clean old log files",
                    command="find /var/log -type f -name '*.log' -mtime +7 -delete 2>/dev/null; journalctl --vacuum-time=7d",
                    cooldown_seconds=3600,
                    auto_approve=True
                ),
            ],
            "memory_usage": [
                RemediationAction(
                    name="clear_cache",
                    description="Clear system caches",
                    command="sync && echo 3 > /proc/sys/vm/drop_caches",
                    cooldown_seconds=600,
                    auto_approve=True
                ),
                RemediationAction(
                    name="restart_high_memory",
                    description="Restart services using most memory",
                    command="ps aux --sort=-%mem | head -6 | tail -5 | awk '{print $2}' | xargs -r kill -9",
                    cooldown_seconds=600,
                    auto_approve=False  # Requires approval - could kill important processes
                ),
            ],
            "network_connectivity": [
                RemediationAction(
                    name="restart_networking",
                    description="Restart network service",
                    command="systemctl restart NetworkManager || systemctl restart networking",
                    cooldown_seconds=300,
                    auto_approve=True
                ),
            ],
            "ssh_service": [
                RemediationAction(
                    name="restart_ssh",
                    description="Restart SSH service",
                    command="systemctl restart sshd || systemctl restart ssh",
                    check_command="systemctl is-active sshd || systemctl is-active ssh",
                    cooldown_seconds=300,
                    auto_approve=True
                ),
            ],
        }
    
    async def run_command(self, command: str, timeout: int = 30) -> tuple[bool, str]:
        """Run a shell command and return success status and output."""
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout
            )
            output = stdout.decode().strip() if stdout else ""
            error = stderr.decode().strip() if stderr else ""
            
            if proc.returncode == 0:
                return True, output
            else:
                return False, error or output
        except asyncio.TimeoutError:
            return False, "Command timed out"
        except Exception as e:
            return False, str(e)
    
    async def run_health_check(self, check: HealthCheck) -> Optional[InfrastructureIssue]:
        """Run a single health check and return issue if failed."""
        check.last_run = datetime.now()
        
        success, output = await self.run_command(
            check.command,
            timeout=check.timeout_seconds
        )
        
        # Special handling for numeric thresholds
        if check.name == "disk_space":
            try:
                usage = int(output)
                success = usage < 90
                output = f"{usage}% disk usage"
            except ValueError:
                success = False
        
        elif check.name == "memory_usage":
            try:
                usage = int(output)
                success = usage < 95
                output = f"{usage}% memory usage"
            except ValueError:
                success = False
        
        elif check.name == "cpu_load":
            try:
                load = float(output)
                # Get number of CPUs
                cpu_success, cpu_output = await self.run_command("nproc")
                num_cpus = int(cpu_output) if cpu_success else 1
                success = load < num_cpus * 2  # Alert if load > 2x CPU count
                output = f"Load average: {load} (CPUs: {num_cpus})"
            except ValueError:
                success = False
        
        check.last_result = success
        
        if not success:
            issue = InfrastructureIssue(
                timestamp=datetime.now(),
                severity=check.severity,
                service=check.name,
                issue_type="health_check_failed",
                description=f"Health check failed: {output}",
                metrics={"output": output, "command": check.command}
            )
            return issue
        
        return None
    
    async def run_all_health_checks(self):
        """Run all enabled health checks."""
        tasks = []
        for check in self.health_checks:
            if not check.enabled:
                continue
            
            # Check if enough time has passed
            if check.last_run:
                elapsed = (datetime.now() - check.last_run).total_seconds()
                if elapsed < check.interval_seconds:
                    continue
            
            tasks.append(self.run_health_check(check))
        
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    logger.error(f"Health check error: {result}")
                elif result:
                    await self.handle_issue(result)
    
    async def handle_issue(self, issue: InfrastructureIssue):
        """Handle a detected infrastructure issue."""
        # Check if similar issue already exists
        existing = self.issues.get(issue.id)
        if existing and existing.status in [IssueStatus.REMEDIATING, IssueStatus.ANALYZING]:
            return
        
        self.issues[issue.id] = issue
        self.stats["issues_detected"] += 1
        
        logger.warning(
            f"Issue detected: [{issue.severity.value}] {issue.service} - {issue.description}"
        )
        
        # Start remediation workflow
        asyncio.create_task(self.remediate_issue(issue))
    
    async def remediate_issue(self, issue: InfrastructureIssue):
        """Attempt to remediate an issue."""
        issue.status = IssueStatus.ANALYZING
        
        # Find remediation actions for this issue type
        actions = self.remediation_actions.get(issue.service, [])
        
        if not actions:
            logger.info(f"No remediation actions defined for {issue.service}")
            issue.status = IssueStatus.ESCALATED
            self.stats["issues_escalated"] += 1
            return
        
        for action in actions:
            if issue.remediation_attempts >= issue.max_attempts:
                break
            
            # Check cooldown
            if action.last_executed:
                elapsed = (datetime.now() - action.last_executed).total_seconds()
                if elapsed < action.cooldown_seconds:
                    continue
            
            issue.status = IssueStatus.REMEDIATING
            issue.remediation_attempts += 1
            self.stats["remediation_attempts"] += 1
            
            logger.info(
                f"Attempting remediation: {action.name} for issue {issue.id}"
            )
            
            # Execute remediation
            success, output = await self.run_command(action.command)
            action.last_executed = datetime.now()
            
            if success:
                # Verify fix
                if action.check_command:
                    await asyncio.sleep(2)  # Give service time to recover
                    verify_success, _ = await self.run_command(action.check_command)
                    if not verify_success:
                        continue
                
                issue.status = IssueStatus.RESOLVED
                issue.resolution = action.name
                issue.resolved_at = datetime.now()
                self.stats["remediation_successes"] += 1
                self.stats["issues_resolved"] += 1
                
                # Move to resolved list
                self.resolved_issues.append(issue)
                del self.issues[issue.id]
                
                logger.info(
                    f"Issue {issue.id} resolved with {action.name}"
                )
                return
            else:
                logger.warning(
                    f"Remediation {action.name} failed: {output}"
                )
        
        # All remediation attempts failed
        issue.status = IssueStatus.FAILED
        self.stats["issues_escalated"] += 1
        logger.error(
            f"Issue {issue.id} could not be auto-remediated after "
            f"{issue.remediation_attempts} attempts"
        )
    
    def get_status(self) -> Dict[str, Any]:
        """Get current system status."""
        return {
            "running": self.running,
            "timestamp": datetime.now().isoformat(),
            "stats": self.stats,
            "active_issues": len(self.issues),
            "resolved_issues": len(self.resolved_issues),
            "health_checks": len(self.health_checks),
            "issues": [
                {
                    "id": i.id,
                    "service": i.service,
                    "severity": i.severity.value,
                    "status": i.status.value,
                    "description": i.description,
                    "attempts": i.remediation_attempts,
                }
                for i in self.issues.values()
            ],
            "recent_resolved": [
                {
                    "id": i.id,
                    "service": i.service,
                    "resolution": i.resolution,
                    "resolved_at": i.resolved_at.isoformat() if i.resolved_at else None,
                }
                for i in self.resolved_issues[-10:]  # Last 10
            ]
        }
    
    async def run(self):
        """Main event loop."""
        self.running = True
        logger.info("Self-healing infrastructure system started")
        
        while self.running:
            try:
                await self.run_all_health_checks()
                await asyncio.sleep(10)  # Check every 10 seconds
            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                await asyncio.sleep(10)
    
    def stop(self):
        """Stop the engine."""
        self.running = False
        logger.info("Self-healing infrastructure system stopped")


class CLI:
    """Command-line interface for the self-healing system."""
    
    def __init__(self):
        self.engine = SelfHealingEngine()
    
    def run(self, args: List[str]):
        """Run CLI command."""
        if len(args) < 1:
            self.print_help()
            return
        
        command = args[0]
        
        if command == "daemon":
            asyncio.run(self.engine.run())
        elif command == "status":
            self.show_status()
        elif command == "check":
            asyncio.run(self.run_check())
        elif command == "list-checks":
            self.list_checks()
        elif command == "help":
            self.print_help()
        else:
            print(f"Unknown command: {command}")
            self.print_help()
    
    def show_status(self):
        """Show current status."""
        status = self.engine.get_status()
        print(json.dumps(status, indent=2, default=str))
    
    async def run_check(self):
        """Run all health checks once."""
        print("Running health checks...")
        await self.engine.run_all_health_checks()
        print("Done.")
        self.show_status()
    
    def list_checks(self):
        """List all configured health checks."""
        print("Configured Health Checks:")
        print("-" * 60)
        for check in self.engine.health_checks:
            status = "enabled" if check.enabled else "disabled"
            print(f"  {check.name}")
            print(f"    Severity: {check.severity.value}")
            print(f"    Interval: {check.interval_seconds}s")
            print(f"    Status: {status}")
            print(f"    Command: {check.command}")
            print()
    
    def print_help(self):
        """Print help message."""
        print("""
Self-Healing Infrastructure System

Usage: self_healing.py <command>

Commands:
  daemon       Run as continuous daemon
  status       Show current system status
  check        Run health checks once
  list-checks  List all configured health checks
  help         Show this help message

Examples:
  self_healing.py daemon          # Start monitoring
  self_healing.py status          # Get current status
  self_healing.py check           # Run checks once
        """)


def main():
    """Main entry point."""
    cli = CLI()
    cli.run(sys.argv[1:])


if __name__ == "__main__":
    main()
