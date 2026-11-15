"""Agent command line: ``python -m auren_agent {scan,run,enroll,run-scan}``.

Exit codes: 0 success, 1 failure, 2 usage error, 3 no scan has been requested.
"""

import argparse
import sys
import uuid
from collections.abc import Sequence
from pathlib import Path

import httpx
import structlog

from auren_agent.benchmark import cpu_chain
from auren_agent.client import ControlPlaneClient, ControlPlaneError
from auren_agent.config import AgentSettings, get_settings
from auren_agent.hardware.linux import LinuxHardwareProbe
from auren_agent.hardware.probe import HardwareProbe, HardwareProbeError
from auren_agent.identity import (
    IdentityError,
    load_machine_id,
    load_or_create_identity,
    save_machine_id,
)
from auren_agent.logging import configure_logging

logger = structlog.get_logger(__name__)

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_NO_SCAN_REQUESTED = 3


class ConfigurationError(Exception):
    """A setting required by the requested command is missing."""


def build_probe(settings: AgentSettings) -> HardwareProbe:
    return LinuxHardwareProbe(
        storage_path=settings.storage_path,
        gpu_probe_timeout_seconds=settings.gpu_probe_timeout_seconds,
    )


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="auren-agent")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("scan", help="print the local hardware inventory as JSON (no network)")
    commands.add_parser(
        "run", help="development mode: scan hardware and log it (no network, no workloads)"
    )
    enroll = commands.add_parser(
        "enroll", help="register this machine's key with the platform (token from the environment)"
    )
    enroll.add_argument("--machine-id", type=uuid.UUID, required=True)
    commands.add_parser(
        "run-scan", help="run the platform scan requested by the provider and submit the result"
    )
    return parser.parse_args(argv)


def _network_settings(settings: AgentSettings) -> tuple[Path, str]:
    if settings.state_dir is None or settings.control_plane_url is None:
        raise ConfigurationError(
            "AUREN_AGENT_STATE_DIR and AUREN_AGENT_CONTROL_PLANE_URL are required for this command"
        )
    return settings.state_dir, settings.control_plane_url


def _enroll(settings: AgentSettings, machine_id: uuid.UUID) -> int:
    state_dir, base_url = _network_settings(settings)
    if settings.enrollment_token is None:
        raise ConfigurationError("AUREN_AGENT_ENROLLMENT_TOKEN is required to enroll")
    identity = load_or_create_identity(state_dir)
    with httpx.Client(timeout=settings.http_timeout_seconds) as http:
        ControlPlaneClient(http, base_url).enroll(
            machine_id, settings.enrollment_token.get_secret_value(), identity.public_key_b64
        )
    save_machine_id(state_dir, machine_id)
    logger.info("agent_enrolled", machine_id=str(machine_id))
    return EXIT_OK


def _run_scan(settings: AgentSettings) -> int:
    state_dir, base_url = _network_settings(settings)
    identity = load_or_create_identity(state_dir)
    machine_id = load_machine_id(state_dir)
    # Read hardware first: the server times the benchmark from when it hands out the challenge.
    inventory = build_probe(settings).scan()
    with httpx.Client(timeout=settings.http_timeout_seconds) as http:
        client = ControlPlaneClient(http, base_url)
        challenge = client.claim_scan(identity.private_key, machine_id)
        if challenge is None:
            logger.info("no_scan_requested")
            return EXIT_NO_SCAN_REQUESTED
        digest = cpu_chain(challenge.challenge, challenge.cpu_iterations)
        result = client.submit_result(
            identity.private_key,
            machine_id,
            challenge.scan_id,
            inventory.model_dump(mode="json"),
            digest,
        )
    logger.info(
        "scan_submitted",
        scan_id=str(challenge.scan_id),
        cpu_hashes_per_second=result["cpu_hashes_per_second"],
        listing_paused=result["listing_paused"],
    )
    return EXIT_OK


def _local(settings: AgentSettings, command: str) -> int:
    inventory = build_probe(settings).scan()
    if command == "scan":
        sys.stdout.write(inventory.model_dump_json(indent=2) + "\n")
        return EXIT_OK
    logger.info(
        "agent_started_development_mode",
        control_plane_connection="disabled",
        workload_execution="disabled",
        logical_cores=inventory.cpu.logical_cores,
        memory_total_bytes=inventory.memory.total_bytes,
        gpu_count=len(inventory.gpus),
    )
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    settings = get_settings()
    configure_logging(settings.log_level)
    try:
        if args.command == "enroll":
            return _enroll(settings, args.machine_id)
        if args.command == "run-scan":
            return _run_scan(settings)
        return _local(settings, args.command)
    except HardwareProbeError as exc:
        logger.error("hardware_scan_failed", reason=str(exc))
    except (ConfigurationError, IdentityError) as exc:
        logger.error("agent_configuration_error", reason=str(exc))
    except ControlPlaneError as exc:
        logger.error("control_plane_rejected_request", status=exc.status, code=exc.code)
    except httpx.HTTPError as exc:
        logger.error("control_plane_unreachable", error=type(exc).__name__)
    return EXIT_FAILURE


if __name__ == "__main__":
    raise SystemExit(main())
