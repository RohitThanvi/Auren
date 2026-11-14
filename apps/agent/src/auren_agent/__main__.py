"""Agent command line: ``python -m auren_agent {scan,status,run}``."""

import argparse
import sys
from collections.abc import Sequence

import structlog

from auren_agent.config import get_settings
from auren_agent.hardware.errors import HardwareProbeError
from auren_agent.logging import configure_logging
from auren_agent.resources.policy import PolicyError
from auren_agent.status import build_probe, collect_status

logger = structlog.get_logger(__name__)


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="auren-agent")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("scan", help="print the hardware inventory as JSON and exit")
    commands.add_parser(
        "status",
        help="print inventory, security capabilities, health, availability and allocatable "
        "capacity as JSON and exit (reads the provider policy if configured)",
    )
    commands.add_parser(
        "run", help="start the agent (development mode: scans hardware, no network, no workloads)"
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    settings = get_settings()
    configure_logging(settings.log_level)
    if args.command == "status":
        try:
            report = collect_status(settings)
        except (HardwareProbeError, PolicyError) as exc:
            logger.error("status_failed", reason=str(exc))
            return 1
        sys.stdout.write(report.model_dump_json(indent=2) + "\n")
        return 0
    try:
        inventory = build_probe(settings).scan()
    except HardwareProbeError as exc:
        logger.error("hardware_scan_failed", reason=str(exc))
        return 1
    if args.command == "scan":
        sys.stdout.write(inventory.model_dump_json(indent=2) + "\n")
        return 0
    logger.info(
        "agent_started_development_mode",
        control_plane_connection="disabled",
        workload_execution="disabled",
        logical_cores=inventory.cpu.logical_cores,
        memory_total_bytes=inventory.memory.total_bytes,
        gpu_count=len(inventory.gpus),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
