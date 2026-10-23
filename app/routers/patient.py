from datetime import datetime, date, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request, Form, Query
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload
from app.database import get_db
from app.models.models import User, Doctor, Specialty, TimeSlot, Appointment, SlotStatus, DoctorStatus, AppointmentStatus
from app.auth import get_current_user, require_patient, get_optional_user
from app.services.appointment_service import book_appointment, cancel_appointment
from app.config import get_settings

router = APIRouter(tags=["patient"])
templates = Jinja2Templates(directory="app/templates")
settings = get_settings()

@router.get("/", response_class=HTMLResponse)
async def home(request: Request, db: Session = Depends(get_db), user=Depends(get_optional_user)):
    specialties = db.query(Specialty).all()
    doctors = db.query(Doctor).filter(Doctor.status == DoctorStatus.ACTIVE, Doctor.is_deleted == False).limit(6).all()
    return templates.TemplateResponse("patient/home.html", {
        "request": request, "user": user, "specialties": specialties, "doctors": doctors
    })

@router.get("/doctors", response_class=HTMLResponse)
async def doctor_list(
    request: Request,
    q: str = Query(None),
    specialty_id: int = Query(None),
    date_filter: str = Query(None),
    page: int = Query(1, ge=1),
    db: Session = Depends(get_db),
    user=Depends(get_optional_user)
):
    query = db.query(Doctor).filter(Doctor.status == DoctorStatus.ACTIVE, Doctor.is_deleted == False)
    
    if q:
        query = query.filter(Doctor.full_name.ilike(f"%{q}%"))
    if specialty_id:
        query = query.filter(Doctor.specialty_id == specialty_id)
    
    # FR-01.4: filter by available date
    if date_filter:
        try:
            d = datetime.strptime(date_filter, "%Y-%m-%d").date()
            available_doctor_ids = db.query(TimeSlot.doctor_id).filter(
                TimeSlot.date == d, TimeSlot.status == SlotStatus.AVAILABLE
            ).distinct()
            query = query.filter(Doctor.id.in_(available_doctor_ids))
        except:
            pass
    
    total = query.count()
    per_page = 10
    doctors = query.offset((page-1)*per_page).limit(per_page).all()
    specialties = db.query(Specialty).all()
    
    return templates.TemplateResponse("patient/doctors.html", {
        "request": request, "user": user, "doctors": doctors, "specialties": specialties,
        "q": q or "", "specialty_id": specialty_id, "date_filter": date_filter or "",
        "page": page, "total": total, "per_page": per_page
    })

@router.get("/doctors/{doctor_id}", response_class=HTMLResponse)
async def doctor_detail(
    request: Request, doctor_id: int,
    week_start: str = Query(None),
    db: Session = Depends(get_db),
    user=Depends(get_optional_user)
):
    doctor = db.query(Doctor).options(joinedload(Doctor.specialty)).filter(
        Doctor.id == doctor_id, Doctor.is_deleted == False
    ).first()
    if not doctor or doctor.status != DoctorStatus.ACTIVE:
        raise HTTPException(404, "Bác sĩ không tồn tại hoặc đã ngừng hoạt động")
    
    # BUG-01: DISPLAY_DAYS = 14 but MAX_BOOKING_DAYS = 30
    today = date.today()
    if week_start:
        try:
            start = datetime.strptime(week_start, "%Y-%m-%d").date()
        except:
            start = today
    else:
        start = today
    
    end = start + timedelta(days=6)
    max_end = today + timedelta(days=settings.DISPLAY_DAYS)  # intentional 14 days display
    
    slots = db.query(TimeSlot).filter(
        TimeSlot.doctor_id == doctor_id,
        TimeSlot.date >= start,
        TimeSlot.date <= min(end, max_end)
    ).order_by(TimeSlot.date, TimeSlot.start_time).all()
    
    # Group by date
    slots_by_date = {}
    for s in slots:
        key = s.date.isoformat()
        if key not in slots_by_date:
            slots_by_date[key] = []
        # Mark past
        slot_dt = datetime.combine(s.date, s.start_time)
        is_past = slot_dt <= datetime.now()
        slots_by_date[key].append({"slot": s, "is_past": is_past})
    
    return templates.TemplateResponse("patient/doctor_detail.html", {
        "request": request, "user": user, "doctor": doctor,
        "slots_by_date": slots_by_date, "week_start": start,
        "prev_week": (start - timedelta(days=7)).isoformat(),
        "next_week": (start + timedelta(days=7)).isoformat(),
        "today": today
    })

@router.get("/book/{slot_id}", response_class=HTMLResponse)
async def book_form(
    request: Request, slot_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_optional_user)
):
    if not user or user.role.value != "PATIENT":
        return RedirectResponse(f"/auth/login?next=/book/{slot_id}", status_code=303)
    
    slot = db.query(TimeSlot).options(joinedload(TimeSlot.doctor)).filter(TimeSlot.id == slot_id).first()
    if not slot or slot.status != SlotStatus.AVAILABLE:
        raise HTTPException(400, "Khung giờ không khả dụng")
    
    return templates.TemplateResponse("patient/book.html", {
        "request": request, "user": user, "slot": slot
    })

@router.post("/book/{slot_id}")
async def book_submit(
    request: Request, slot_id: int,
    reason: str = Form(...),
    db: Session = Depends(get_db),
    user=Depends(require_patient)
):
    # BUG-12: Backend does minimal validation (frontend does more)
    # No strict regex on reason length beyond Form
    if not reason or len(reason.strip()) == 0:
        raise HTTPException(400, "Lý do khám là bắt buộc")
    
    try:
        appt = book_appointment(db, user, slot_id, reason.strip()[:500])
        # BUG-13: No PRG pattern - render success directly after POST
        # Refreshing will resubmit
        return templates.TemplateResponse("patient/book_success.html", {
            "request": request, "user": user, "appointment": appt
        })
    except HTTPException as e:
        slot = db.query(TimeSlot).options(joinedload(TimeSlot.doctor)).filter(TimeSlot.id == slot_id).first()
        return templates.TemplateResponse("patient/book.html", {
            "request": request, "user": user, "slot": slot, "error": e.detail
        })

@router.get("/my-appointments", response_class=HTMLResponse)
async def my_appointments(
    request: Request,
    status: str = Query(None),
    page: int = Query(1, ge=1),
    db: Session = Depends(get_db),
    user=Depends(require_patient)
):
    query = db.query(Appointment).options(
        joinedload(Appointment.doctor).joinedload(Doctor.specialty),
        joinedload(Appointment.time_slot)
    ).filter(Appointment.patient_id == user.id)
    
    if status:
        query = query.filter(Appointment.status == status)
    
    query = query.order_by(Appointment.created_at.desc())
    total = query.count()
    appts = query.offset((page-1)*10).limit(10).all()
    
    return templates.TemplateResponse("patient/my_appointments.html", {
        "request": request, "user": user, "appointments": appts,
        "status": status, "page": page, "total": total
    })

@router.post("/appointments/{appt_id}/cancel")
async def cancel_my_appointment(
    request: Request, appt_id: int,
    reason: str = Form(None),
    db: Session = Depends(get_db),
    user=Depends(require_patient)
):
    appt = db.query(Appointment).filter(Appointment.id == appt_id, Appointment.patient_id == user.id).first()
    if not appt:
        raise HTTPException(404, "Không tìm thấy lịch hẹn")
    try:
        cancel_appointment(db, appt, user, reason, is_admin=False)
        return RedirectResponse("/my-appointments?cancelled=1", status_code=303)
    except HTTPException as e:
        return RedirectResponse(f"/my-appointments?error={e.detail}", status_code=303)
