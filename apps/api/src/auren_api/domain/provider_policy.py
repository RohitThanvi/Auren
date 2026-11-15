"""Operator-configured limits for providers, assembled once from settings."""

from dataclasses import dataclass

from auren_api.config import Settings
from auren_api.domain.money import Currency, Money
from auren_api.domain.pricing import RateCard


@dataclass(frozen=True, slots=True)
class ProviderPolicy:
    rate_card: RateCard
    max_allocatable_bps: int
    max_machines: int
    max_hosting_hours: int
    scan_ttl_seconds: int
    scan_result_deadline_seconds: int
    scan_cpu_iterations: int
    enrollment_ttl_seconds: int


def provider_policy_from_settings(settings: Settings) -> ProviderPolicy:
    currency = Currency.INR
    return ProviderPolicy(
        rate_card=RateCard(
            cpu_core_hour=Money(settings.pricing_cpu_core_hour_minor, currency),
            memory_gib_hour=Money(settings.pricing_memory_gib_hour_minor, currency),
            gpu_vram_gib_hour=Money(settings.pricing_gpu_vram_gib_hour_minor, currency),
            storage_100gib_hour=Money(settings.pricing_storage_100gib_hour_minor, currency),
            floor_bps=settings.pricing_floor_bps,
            ceiling_bps=settings.pricing_ceiling_bps,
            confidential_premium_bps=settings.pricing_confidential_premium_bps,
        ),
        max_allocatable_bps=settings.provider_max_allocatable_bps,
        max_machines=settings.provider_max_machines,
        max_hosting_hours=settings.provider_max_hosting_hours,
        scan_ttl_seconds=settings.scan_ttl_seconds,
        scan_result_deadline_seconds=settings.scan_result_deadline_seconds,
        scan_cpu_iterations=settings.scan_cpu_iterations,
        enrollment_ttl_seconds=settings.enrollment_ttl_seconds,
    )
