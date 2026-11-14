"""Provider endpoints: self-service enrolment, machines, scans, pricing and listings.

Every machine route is owner-scoped in the service layer; machines of other users are reported
as not found.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from auren_api.api.deps import (
    PrincipalDep,
    ProviderServiceDep,
    SessionDep,
    limit_by_user,
    require_roles,
)
from auren_api.auth.principal import Principal
from auren_api.domain.money import Money
from auren_api.domain.roles import Role
from auren_api.infrastructure.rate_limit import RateLimitPolicy
from auren_api.schemas.common import ErrorResponse
from auren_api.schemas.provider import (
    AllocatableRequest,
    CreateMachineRequest,
    InventoryAcceptedResponse,
    InventoryReport,
    InventorySummaryResponse,
    ListingRequest,
    ListingResponse,
    MachineResponse,
    MoneyResponse,
    PriceRangeResponse,
)
from auren_api.schemas.users import MeResponse
from auren_api.services.provider import InventoryView, MachineView
from auren_api.services.users import UserAccount, UserService

router = APIRouter(
    prefix="/provider",
    tags=["provider"],
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)

ProviderDep = Annotated[Principal, Depends(require_roles(Role.PROVIDER))]
_machine_limit = Depends(limit_by_user(RateLimitPolicy.AUTHENTICATED))


def _money(value: Money) -> MoneyResponse:
    return MoneyResponse(amount_minor=value.amount_minor, currency=value.currency)


def _inventory(view: InventoryView) -> InventorySummaryResponse:
    return InventorySummaryResponse(
        id=view.id,
        received_at=view.received_at,
        logical_cores=view.logical_cores,
        memory_total_bytes=view.memory_total_bytes,
        storage_total_bytes=view.storage_total_bytes,
        gpu_count=view.gpu_count,
        hardware_virtualization=view.hardware_virtualization,
        kvm_available=view.kvm_available,
        confidential_computing_flags=list(view.confidential_computing_flags),
    )


def _machine(view: MachineView) -> MachineResponse:
    listing = view.listing
    return MachineResponse(
        id=view.id,
        name=view.name,
        status=view.status,
        created_at=view.created_at,
        inventory=_inventory(view.inventory) if view.inventory else None,
        listing=ListingResponse(
            price_per_hour=_money(listing.price),
            cpu_cores=listing.allocatable.cpu_cores,
            memory_bytes=listing.allocatable.memory_bytes,
            gpu_indices=list(listing.allocatable.gpu_indices),
            storage_bytes=listing.allocatable.storage_bytes,
            max_hosting_hours=listing.max_hosting_hours,
        )
        if listing
        else None,
    )


@router.post(
    "/enable",
    response_model=MeResponse,
    summary="Become a provider (self-service)",
    dependencies=[Depends(limit_by_user(RateLimitPolicy.AUTH))],
)
async def enable_provider(principal: PrincipalDep, session: SessionDep) -> MeResponse:
    account = await UserService(session).enable_provider(
        UserAccount(
            id=principal.user_id, clerk_user_id=principal.clerk_user_id, roles=principal.roles
        )
    )
    return MeResponse(id=account.id, roles=sorted(account.roles))


@router.post(
    "/machines",
    response_model=MachineResponse,
    status_code=201,
    summary="Register a machine",
    dependencies=[_machine_limit],
)
async def create_machine(
    body: CreateMachineRequest, principal: ProviderDep, service: ProviderServiceDep
) -> MachineResponse:
    return _machine(await service.create_machine(principal.user_id, body.name))


@router.get(
    "/machines",
    response_model=list[MachineResponse],
    summary="List my machines (bounded by the per-provider machine limit)",
    dependencies=[_machine_limit],
)
async def list_machines(
    principal: ProviderDep, service: ProviderServiceDep
) -> list[MachineResponse]:
    return [_machine(view) for view in await service.list_machines(principal.user_id)]


@router.get(
    "/machines/{machine_id}",
    response_model=MachineResponse,
    summary="Get one of my machines",
    dependencies=[_machine_limit],
)
async def get_machine(
    machine_id: UUID, principal: ProviderDep, service: ProviderServiceDep
) -> MachineResponse:
    return _machine(await service.get_machine(principal.user_id, machine_id))


@router.put(
    "/machines/{machine_id}/inventory",
    response_model=InventoryAcceptedResponse,
    summary="Submit a hardware scan (self-reported)",
    dependencies=[_machine_limit],
)
async def submit_inventory(
    machine_id: UUID,
    body: InventoryReport,
    principal: ProviderDep,
    service: ProviderServiceDep,
) -> InventoryAcceptedResponse:
    accepted = await service.submit_inventory(
        principal.user_id,
        machine_id,
        body.to_snapshot(),
        body.cpu.confidential_computing_flags,
        body.model_dump(mode="json"),
    )
    return InventoryAcceptedResponse(
        inventory=_inventory(accepted.inventory), listing_paused=accepted.listing_paused
    )


@router.post(
    "/machines/{machine_id}/price-range",
    response_model=PriceRangeResponse,
    summary="Price range for an offered allocation",
    dependencies=[_machine_limit],
)
async def price_range(
    machine_id: UUID,
    body: AllocatableRequest,
    principal: ProviderDep,
    service: ProviderServiceDep,
) -> PriceRangeResponse:
    band = await service.price_range(principal.user_id, machine_id, body.to_domain())
    return PriceRangeResponse(
        base=_money(band.base), floor=_money(band.floor), ceiling=_money(band.ceiling)
    )


@router.put(
    "/machines/{machine_id}/listing",
    response_model=MachineResponse,
    summary="List the machine at a price inside the allowed range",
    dependencies=[_machine_limit],
)
async def set_listing(
    machine_id: UUID,
    body: ListingRequest,
    principal: ProviderDep,
    service: ProviderServiceDep,
) -> MachineResponse:
    view = await service.set_listing(
        principal.user_id,
        machine_id,
        body.to_domain(),
        body.price_per_hour_minor,
        body.max_hosting_hours,
    )
    return _machine(view)


@router.post(
    "/machines/{machine_id}/pause",
    response_model=MachineResponse,
    summary="Pause hosting",
    dependencies=[_machine_limit],
)
async def pause_machine(
    machine_id: UUID, principal: ProviderDep, service: ProviderServiceDep
) -> MachineResponse:
    return _machine(await service.pause(principal.user_id, machine_id))


@router.post(
    "/machines/{machine_id}/resume",
    response_model=MachineResponse,
    summary="Resume hosting",
    dependencies=[_machine_limit],
)
async def resume_machine(
    machine_id: UUID, principal: ProviderDep, service: ProviderServiceDep
) -> MachineResponse:
    return _machine(await service.resume(principal.user_id, machine_id))


@router.post(
    "/machines/{machine_id}/withdraw",
    response_model=MachineResponse,
    summary="Withdraw the machine permanently",
    dependencies=[_machine_limit],
)
async def withdraw_machine(
    machine_id: UUID, principal: ProviderDep, service: ProviderServiceDep
) -> MachineResponse:
    return _machine(await service.withdraw(principal.user_id, machine_id))
