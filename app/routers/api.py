"""
API endpoints intentionally vulnerable for BUG-11, BUG-12 testing.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from app.database import get_db
from app.models.models import User, TimeSlot, Appointment, SlotStatus, AppointmentStatus
from app.auth import get_current_user, require_patient
from app.services.appointment_service import book_appointment, generate_appointment_code
from datetime import datetime

router = APIRouter(prefix="/api", tags=["api"])

class BookRequest(BaseModel):
    timeslot_id: int
    reason: str
    # Intentionally weak: no validation on reason length, phone, etc. (BUG-12)

class BookResponse(BaseModel):
    success: bool
    code: Optional[str] = None
    message: str

@router.post("/appointments/book", response_model=BookResponse)
async def api_book(
    body: BookRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_patient)
):
    """
    BUG-11: Race condition - no SELECT FOR UPDATE.
    BUG-12: Minimal server-side validation.
    """
    # Almost no validation beyond what's in book_appointment
    try:
        appt = book_appointment(db, user, body.timeslot_id, body.reason)
        return BookResponse(success=True, code=appt.code, message="Đặt lịch thành công")
    except HTTPException as e:
        return BookResponse(success=False, message=str(e.detail))

@router.get("/slots/{slot_id}")
async def get_slot(slot_id: int, db: Session = Depends(get_db)):
    slot = db.query(TimeSlot).filter(TimeSlot.id == slot_id).first()
    if not slot:
        raise HTTPException(404)
    return {
        "id": slot.id,
        "doctor_id": slot.doctor_id,
        "date": str(slot.date),
        "start": str(slot.start_time),
        "end": str(slot.end_time),
        "status": slot.status.value
    }
