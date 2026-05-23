from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import APIKey
from ..services.auth import require_permission
from ..services.export import generate_pdf, stream_csv

router = APIRouter(prefix="/export", tags=["export"])


@router.get("/csv")
async def export_csv(
    start_date: Optional[datetime] = Query(default=None),
    end_date: Optional[datetime] = Query(default=None),
    agent_name: Optional[str] = Query(default=None),
    action_type: Optional[str] = Query(default=None),
    result: Optional[str] = Query(default=None),
    limit: int = Query(default=5000, le=10_000, ge=1),
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey | None] = Depends(require_permission("read")),
):
    """Stream action records as CSV. Respects the same filters as GET /v1/actions."""
    org_id, _ = auth
    filters = {
        "start_date": start_date,
        "end_date": end_date,
        "agent_name": agent_name,
        "action_type": action_type,
        "result": result,
        "limit": limit,
    }
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"vera_export_{timestamp}.csv"
    return StreamingResponse(
        stream_csv(session, org_id, filters),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/pdf")
async def export_pdf(
    start_date: Optional[datetime] = Query(default=None),
    end_date: Optional[datetime] = Query(default=None),
    agent_name: Optional[str] = Query(default=None),
    action_type: Optional[str] = Query(default=None),
    result: Optional[str] = Query(default=None),
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey | None] = Depends(require_permission("read")),
):
    """Generate a compliance audit PDF. Includes chain status, checkpoints, and records.
    Capped at 5000 records to keep the PDF readable."""
    org_id, _ = auth
    filters = {
        "start_date": start_date,
        "end_date": end_date,
        "agent_name": agent_name,
        "action_type": action_type,
        "result": result,
    }
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"vera_report_{timestamp}.pdf"
    pdf_bytes = await generate_pdf(session, org_id, filters)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
