from datetime import datetime, date, time, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request, Form, Query, UploadFile, File
from fastapi.responses import RedirectResponse, HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload
from app.database import get_db
from app.models.models import (
    User, Doctor, Specialty, TimeSlot, Appointment, AppointmentLog,
    DoctorStatus, SlotStatus, AppointmentStatus
)
from app.auth import require_admin
from app.services.appointment_service import (
    admin_confirm, cancel_appointment, admin_complete_or_noshow, run_background_jobs
)
from app.config import get_settings
import os, io, csv

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory="app/templates")
settings = get_settings()

@router.get("", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db), admin=Depends(require_admin)):
    today = date.today()
    today_count = db.query(Appointment).join(TimeSlot).filter(TimeSlot.date == today).count()
    pending_count = db.query(Appointment).filter(Appointment.status == AppointmentStatus.PENDING).count()
    week_start = today - timedelta(days=today.weekday())
    cancelled_week = db.query(Appointment).filter(
        Appointment.status == AppointmentStatus.CANCELLED,
        Appointment.updated_at >= datetime.combine(week_start, time.min)
    ).count()
    
    # Urgent: pending < 1h before start
    urgent = []
    pendings = db.query(Appointment).options(
        joinedload(Appointment.time_slot), joinedload(Appointment.patient), joinedload(Appointment.doctor)
    ).filter(Appointment.status == AppointmentStatus.PENDING).all()
    now = datetime.now()
    for p in pendings:
        if p.time_slot:
            slot_dt = datetime.combine(p.time_slot.date, p.time_slot.start_time)
            if 0 < (slot_dt - now).total_seconds() < 3600:
                urgent.append(p)
    
    return templates.TemplateResponse("admin/dashboard.html", {
        "request": request, "user": admin,
        "today_count": today_count, "pending_count": pending_count,
        "cancelled_week": cancelled_week, "urgent": urgent
    })

@router.get("/doctors", response_class=HTMLResponse)
async def manage_doctors(
    request: Request, q: str = Query(None), specialty_id: int = Query(None),
    status: str = Query(None), page: int = 1,
    db: Session = Depends(get_db), admin=Depends(require_admin)
):
    query = db.query(Doctor).filter(Doctor.is_deleted == False)
    if q:
        query = query.filter(Doctor.full_name.ilike(f"%{q}%"))
    if specialty_id:
        query = query.filter(Doctor.specialty_id == specialty_id)
    if status:
        query = query.filter(Doctor.status == status)
    
    total = query.count()
    doctors = query.offset((page-1)*10).limit(10).all()
    specialties = db.query(Specialty).all()
    return templates.TemplateResponse("admin/doctors.html", {
        "request": request, "user": admin, "doctors": doctors,
        "specialties": specialties, "q": q or "", "specialty_id": specialty_id,
        "status": status, "page": page, "total": total
    })

@router.get("/doctors/add", response_class=HTMLResponse)
async def add_doctor_form(request: Request, db: Session = Depends(get_db), admin=Depends(require_admin)):
    specialties = db.query(Specialty).all()
    return templates.TemplateResponse("admin/doctor_form.html", {
        "request": request, "user": admin, "specialties": specialties, "doctor": None
    })

@router.post("/doctors/add")
async def add_doctor(
    request: Request,
    full_name: str = Form(...), specialty_id: int = Form(...),
    email: str = Form(...), phone: str = Form(...),
    degree: str = Form(None), experience_years: int = Form(0),
    bio: str = Form(None), consultation_fee: int = Form(0),
    avatar: UploadFile = File(None),
    db: Session = Depends(get_db), admin=Depends(require_admin)
):
    if db.query(Doctor).filter(Doctor.email == email).first():
        specialties = db.query(Specialty).all()
        return templates.TemplateResponse("admin/doctor_form.html", {
            "request": request, "user": admin, "specialties": specialties,
            "error": "Email bác sĩ đã tồn tại", "doctor": None
        })
    
    avatar_path = None
    if avatar and avatar.filename:
        # BUG-05: config says 5MB, but we could enforce either; using 5MB here
        content = await avatar.read()
        if len(content) > settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
            raise HTTPException(400, f"Ảnh tối đa {settings.MAX_UPLOAD_SIZE_MB}MB")
        os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
        ext = os.path.splitext(avatar.filename)[1].lower()
        if ext not in [".jpg", ".jpeg", ".png"]:
            raise HTTPException(400, "Chỉ chấp nhận JPG/PNG")
        fname = f"doctor_{datetime.now().strftime('%Y%m%d%H%M%S')}{ext}"
        path = os.path.join(settings.UPLOAD_DIR, fname)
        with open(path, "wb") as f:
            f.write(content)
        avatar_path = f"/static/uploads/{fname}"
    
    doctor = Doctor(
        full_name=full_name, specialty_id=specialty_id, email=email, phone=phone,
        degree=degree, experience_years=experience_years, bio=bio,
        consultation_fee=consultation_fee, avatar=avatar_path
    )
    db.add(doctor)
    db.commit()
    return RedirectResponse("/admin/doctors", status_code=303)

@router.post("/doctors/{doctor_id}/toggle-status")
async def toggle_doctor_status(
    doctor_id: int, db: Session = Depends(get_db), admin=Depends(require_admin)
):
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id, Doctor.is_deleted == False).first()
    if not doctor:
        raise HTTPException(404)
    
    # BUG-08: Allow setting INACTIVE even if future appointments exist
    # (FR-06.4 only restricts hard delete, not soft inactive)
    if doctor.status == DoctorStatus.ACTIVE:
        doctor.status = DoctorStatus.INACTIVE
    else:
        doctor.status = DoctorStatus.ACTIVE
    db.commit()
    return RedirectResponse("/admin/doctors", status_code=303)

@router.get("/slots", response_class=HTMLResponse)
async def manage_slots(
    request: Request, doctor_id: int = Query(None),
    week_start: str = Query(None),
    db: Session = Depends(get_db), admin=Depends(require_admin)
):
    doctors = db.query(Doctor).filter(Doctor.is_deleted == False, Doctor.status == DoctorStatus.ACTIVE).all()
    slots = []
    selected_doctor = None
    start = date.today()
    if week_start:
        try:
            start = datetime.strptime(week_start, "%Y-%m-%d").date()
        except:
            pass
    end = start + timedelta(days=6)
    
    if doctor_id:
        selected_doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
        slots = db.query(TimeSlot).filter(
            TimeSlot.doctor_id == doctor_id,
            TimeSlot.date >= start, TimeSlot.date <= end
        ).order_by(TimeSlot.date, TimeSlot.start_time).all()
    
    return templates.TemplateResponse("admin/slots.html", {
        "request": request, "user": admin, "doctors": doctors,
        "selected_doctor": selected_doctor, "slots": slots,
        "week_start": start, "doctor_id": doctor_id
    })

@router.post("/slots/generate")
async def generate_slots(
    doctor_id: int = Form(...),
    start_date: str = Form(...),
    end_date: str = Form(...),
    start_hour: int = Form(8),
    end_hour: int = Form(17),
    slot_minutes: int = Form(30),
    db: Session = Depends(get_db), admin=Depends(require_admin)
):
    s_date = datetime.strptime(start_date, "%Y-%m-%d").date()
    e_date = datetime.strptime(end_date, "%Y-%m-%d").date()
    if s_date < date.today():
        raise HTTPException(400, "Không tạo khung giờ trong quá khứ")
    
    current = s_date
    created = 0
    while current <= e_date:
        hour = start_hour
        while hour < end_hour:
            st = time(hour, 0)
            minutes = hour * 60 + slot_minutes
            et = time(minutes // 60, minutes % 60)
            exists = db.query(TimeSlot).filter(
                TimeSlot.doctor_id == doctor_id,
                TimeSlot.date == current,
                TimeSlot.start_time == st
            ).first()
            if not exists:
                slot = TimeSlot(
                    doctor_id=doctor_id, date=current,
                    start_time=st, end_time=et, status=SlotStatus.AVAILABLE
                )
                db.add(slot)
                created += 1
            hour_minutes = hour * 60 + slot_minutes
            hour = hour_minutes // 60
            if hour_minutes % 60 != 0:
                # for non-hour aligned, simplify by advancing full slot
                pass
            else:
                hour = hour  # already advanced
            # simpler loop
            from datetime import datetime as dt
            t = dt.combine(current, st) + timedelta(minutes=slot_minutes)
            if t.time() >= time(end_hour, 0):
                break
            hour = t.hour
            if t.minute:
                # next start
                st = t.time()
            else:
                st = time(hour, 0)
        current += timedelta(days=1)
    db.commit()
    return RedirectResponse(f"/admin/slots?doctor_id={doctor_id}", status_code=303)

@router.post("/slots/{slot_id}/block")
async def block_slot(slot_id: int, db: Session = Depends(get_db), admin=Depends(require_admin)):
    slot = db.query(TimeSlot).filter(TimeSlot.id == slot_id).first()
    if not slot:
        raise HTTPException(404)
    
    if slot.status == SlotStatus.BOOKED:
        # FR-07.8: cancel related appointment
        appt = db.query(Appointment).filter(
            Appointment.timeslot_id == slot_id,
            Appointment.status.in_([AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED])
        ).first()
        if appt:
            # BUG-06: cancel_appointment sets slot to AVAILABLE, then we set BLOCKED
            # but if order wrong, conflict arises
            cancel_appointment(db, appt, admin, reason="Admin khóa khung giờ", is_admin=True)
    
    slot.status = SlotStatus.BLOCKED
    db.commit()
    return RedirectResponse(f"/admin/slots?doctor_id={slot.doctor_id}", status_code=303)

@router.get("/appointments", response_class=HTMLResponse)
async def manage_appointments(
    request: Request,
    status: str = Query(None), doctor_id: int = Query(None),
    date_from: str = Query(None), q: str = Query(None),
    page: int = 1,
    db: Session = Depends(get_db), admin=Depends(require_admin)
):
    query = db.query(Appointment).options(
        joinedload(Appointment.patient),
        joinedload(Appointment.doctor),
        joinedload(Appointment.time_slot)
    )
    if status:
        query = query.filter(Appointment.status == status)
    if doctor_id:
        query = query.filter(Appointment.doctor_id == doctor_id)
    if q:
        query = query.filter(
            (Appointment.code.ilike(f"%{q}%")) |
            (Appointment.patient.has(User.full_name.ilike(f"%{q}%")))
        )
    
    total = query.count()
    appts = query.order_by(Appointment.created_at.desc()).offset((page-1)*15).limit(15).all()
    doctors = db.query(Doctor).filter(Doctor.is_deleted == False).all()
    
    return templates.TemplateResponse("admin/appointments.html", {
        "request": request, "user": admin, "appointments": appts,
        "doctors": doctors, "status": status, "doctor_id": doctor_id,
        "q": q or "", "page": page, "total": total
    })

@router.post("/appointments/{appt_id}/action")
async def appointment_action(
    appt_id: int, action: str = Form(...), reason: str = Form(None),
    db: Session = Depends(get_db), admin=Depends(require_admin)
):
    appt = db.query(Appointment).filter(Appointment.id == appt_id).first()
    if not appt:
        raise HTTPException(404)
    
    if action == "confirm":
        admin_confirm(db, appt, admin)  # BUG-07: no past-time check
    elif action == "cancel":
        cancel_appointment(db, appt, admin, reason or "Admin hủy", is_admin=True)
    elif action in ("complete", "no_show"):
        admin_complete_or_noshow(db, appt, admin, action)
    
    return RedirectResponse("/admin/appointments", status_code=303)

@router.get("/specialties", response_class=HTMLResponse)
async def manage_specialties(request: Request, db: Session = Depends(get_db), admin=Depends(require_admin)):
    specs = db.query(Specialty).all()
    return templates.TemplateResponse("admin/specialties.html", {
        "request": request, "user": admin, "specialties": specs
    })

@router.post("/specialties/add")
async def add_specialty(name: str = Form(...), description: str = Form(None),
                        db: Session = Depends(get_db), admin=Depends(require_admin)):
    if db.query(Specialty).filter(Specialty.name == name).first():
        raise HTTPException(400, "Chuyên khoa đã tồn tại")
    db.add(Specialty(name=name, description=description))
    db.commit()
    return RedirectResponse("/admin/specialties", status_code=303)

@router.post("/run-jobs")
async def trigger_jobs(db: Session = Depends(get_db), admin=Depends(require_admin)):
    run_background_jobs(db)
    return RedirectResponse("/admin", status_code=303)
