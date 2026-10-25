"""Fault injection switch for Experiment E1 (staff key required)."""
import logging

from fastapi import APIRouter, Depends

from ..auth import require_staff
from ..errors import error_responses
from ..faults import faults
from ..observability.logs import log_event
from ..schemas import FaultConfig

router = APIRouter(prefix="/admin/faults", tags=["admin"], dependencies=[Depends(require_staff)],
                   responses=error_responses(401, 422))
logger = logging.getLogger("campus.admin")


@router.get("")
def read_faults():
    return faults.config


@router.post("")
def set_faults(body: FaultConfig):
    faults.set(body)
    log_event(logger, logging.WARNING, "fault_configured", "fault injection settings changed", **body.model_dump())
    return faults.config


@router.delete("")
def clear_faults():
    faults.clear()
    log_event(logger, logging.WARNING, "fault_cleared", "fault injection switched off")
    return faults.config
