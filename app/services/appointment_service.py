from datetime import datetime, date, time, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from fastapi import HTTPException
from app.models.models import (
    Appointment, TimeSlot, User, Doctor, AppointmentLog, 
    AppointmentStatus, SlotStatus, Notification, NotificationChannel, NotificationStatus
)
from app.config import get_settings
import random

settings = get_settings()

def generate_appointment_code(db: Session) -> str:
    today = datetime.now().strftime("%Y%m%d")
    prefix = f"LH-{today}-"
    last = db.query(Appointment).filter(Appointment.code.like(f"{prefix}%")).order_by(Appointment.id.desc()).first()
    if last:
        try:
            num = int(last.code.split("-")[-1]) + 1
        except:
            num = 1
    else:
        num = 1
    return f"{prefix}{num:04d}"

def check_overlap(start_a: time, end_a: time, start_b: time, end_b: time) -> bool:
    """Two intervals overlap if Start_A < End_B and Start_B < End_A. Adjacent is OK."""
    return start_a < end_b and start_b < end_a

def get_patient_active_appointments(db: Session, patient_id: int):
    return db.query(Appointment).filter(
        Appointment.patient_id == patient_id,
        Appointment.status.in_([AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED])
    ).all()

def book_appointment(db: Session, patient: User, timeslot_id: int, reason: str) -> Appointment:
    """
    Book an appointment.
    BUG-10: Missing patient-level lock. Only checks slot, no lock on patient.
    BUG-11: No SELECT FOR UPDATE / pessimistic lock on slot -> Race condition possible.
    """
    # BUG-11: No transaction lock on the slot
    slot = db.query(TimeSlot).filter(TimeSlot.id == timeslot_id).first()
    if not slot:
        raise HTTPException(404, "Khung giờ không tồn tại")
    
    if slot.status != SlotStatus.AVAILABLE:
        raise HTTPException(400, "Khung giờ đã được đặt, vui lòng chọn giờ khác")
    
    # Check past / min hours
    now = datetime.now()
    slot_dt = datetime.combine(slot.date, slot.start_time)
    if slot_dt <= now:
        raise HTTPException(400, "Không thể đặt khung giờ trong quá khứ hoặc đã bắt đầu")
    
    min_delta = timedelta(hours=settings.MIN_BOOKING_HOURS)
    if slot_dt - now < min_delta:
        raise HTTPException(400, f"Chỉ được đặt lịch trước tối thiểu {settings.MIN_BOOKING_HOURS} giờ")
    
    max_delta = timedelta(days=settings.MAX_BOOKING_DAYS)
    if slot_dt - now > max_delta:
        raise HTTPException(400, f"Chỉ được đặt lịch trong tối đa {settings.MAX_BOOKING_DAYS} ngày")
    
    # Check max active appointments
    active = get_patient_active_appointments(db, patient.id)
    if len(active) >= settings.MAX_ACTIVE_APPOINTMENTS:
        raise HTTPException(400, f"Bạn đã có tối đa {settings.MAX_ACTIVE_APPOINTMENTS} lịch hẹn đang hoạt động")
    
    # Check overlap with patient's other appointments (FR-03.7)
    # BUG-10: No patient lock - concurrent requests from same patient can pass
    for appt in active:
        other_slot = appt.time_slot
        if other_slot and other_slot.date == slot.date:
            if check_overlap(slot.start_time, slot.end_time, other_slot.start_time, other_slot.end_time):
                raise HTTPException(
                    400, 
                    f"Trùng giờ với lịch {appt.code} (BS {appt.doctor.full_name}, {other_slot.start_time.strftime('%H:%M')}-{other_slot.end_time.strftime('%H:%M')})"
                )
    
    # Create appointment
    code = generate_appointment_code(db)
    appt = Appointment(
        code=code,
        patient_id=patient.id,
        doctor_id=slot.doctor_id,
        timeslot_id=slot.id,
        reason=reason,
        status=AppointmentStatus.PENDING
    )
    slot.status = SlotStatus.BOOKED
    db.add(appt)
    db.flush()
    
    # Log
    log = AppointmentLog(
        appointment_id=appt.id,
        old_status=None,
        new_status=AppointmentStatus.PENDING.value,
        performed_by=f"PATIENT:{patient.id}"
    )
    db.add(log)
    db.commit()
    db.refresh(appt)
    return appt

def cancel_appointment(db: Session, appt: Appointment, by_user: User, reason: str = None, is_admin: bool = False):
    if appt.status not in [AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED]:
        raise HTTPException(400, "Lịch hẹn không thể hủy ở trạng thái hiện tại")
    
    if not is_admin:
        # BR-05: patient must cancel at least MIN_CANCEL_HOURS before
        slot = appt.time_slot
        slot_dt = datetime.combine(slot.date, slot.start_time)
        if slot_dt - datetime.now() < timedelta(hours=settings.MIN_CANCEL_HOURS):
            raise HTTPException(400, f"Chỉ được hủy trước giờ khám tối thiểu {settings.MIN_CANCEL_HOURS} giờ")
    
    old = appt.status
    appt.status = AppointmentStatus.CANCELLED
    appt.cancel_reason = reason
    appt.cancelled_by = "ADMIN" if is_admin else "PATIENT"
    appt.updated_at = datetime.utcnow()
    
    # Release slot (BR-06)
    # BUG-06: When admin locks/deletes slot, this still sets AVAILABLE, conflicting with BLOCKED intent
    if appt.time_slot:
        appt.time_slot.status = SlotStatus.AVAILABLE
    
    log = AppointmentLog(
        appointment_id=appt.id,
        old_status=old.value,
        new_status=AppointmentStatus.CANCELLED.value,
        performed_by=f"{'ADMIN' if is_admin else 'PATIENT'}:{by_user.id}"
    )
    db.add(log)
    
    # Notify patient if admin cancelled
    if is_admin and appt.patient_id != by_user.id:
        notif = Notification(
            user_id=appt.patient_id,
            appointment_id=appt.id,
            type="HỦY_LỊCH",
            content=f"Lịch hẹn {appt.code} đã bị hủy bởi Admin. Lý do: {reason or 'Không có'}",
            channel=NotificationChannel.IN_APP
        )
        db.add(notif)
    
    db.commit()
    return appt

def admin_confirm(db: Session, appt: Appointment, admin: User):
    # BUG-07: No check if appointment time has already passed
    if appt.status != AppointmentStatus.PENDING:
        raise HTTPException(400, "Chỉ xác nhận được lịch ở trạng thái Chờ xác nhận")
    
    old = appt.status
    appt.status = AppointmentStatus.CONFIRMED
    appt.updated_at = datetime.utcnow()
    
    log = AppointmentLog(
        appointment_id=appt.id,
        old_status=old.value,
        new_status=AppointmentStatus.CONFIRMED.value,
        performed_by=f"ADMIN:{admin.id}"
    )
    db.add(log)
    db.commit()
    return appt

def admin_complete_or_noshow(db: Session, appt: Appointment, admin: User, action: str):
    if appt.status != AppointmentStatus.CONFIRMED:
        raise HTTPException(400, "Chỉ áp dụng cho lịch Đã xác nhận")
    
    old = appt.status
    if action == "complete":
        appt.status = AppointmentStatus.COMPLETED
    elif action == "no_show":
        appt.status = AppointmentStatus.NO_SHOW
    else:
        raise HTTPException(400, "Action không hợp lệ")
    
    appt.updated_at = datetime.utcnow()
    log = AppointmentLog(
        appointment_id=appt.id,
        old_status=old.value,
        new_status=appt.status.value,
        performed_by=f"ADMIN:{admin.id}"
    )
    db.add(log)
    db.commit()
    return appt

def run_background_jobs(db: Session):
    """Periodic jobs: auto-cancel pending past start, auto overdue confirmed."""
    now = datetime.now()
    
    # BR-11: Auto cancel PENDING that reached start time
    pending = db.query(Appointment).filter(Appointment.status == AppointmentStatus.PENDING).all()
    for appt in pending:
        slot = appt.time_slot
        if not slot:
            continue
        slot_dt = datetime.combine(slot.date, slot.start_time)
        if now >= slot_dt:
            old = appt.status
            appt.status = AppointmentStatus.CANCELLED
            appt.cancel_reason = "Quá hạn xác nhận"
            appt.cancelled_by = "SYSTEM"
            if slot:
                slot.status = SlotStatus.AVAILABLE
            log = AppointmentLog(
                appointment_id=appt.id,
                old_status=old.value,
                new_status=AppointmentStatus.CANCELLED.value,
                performed_by="SYSTEM"
            )
            db.add(log)
            notif = Notification(
                user_id=appt.patient_id,
                appointment_id=appt.id,
                type="QUÁ_HẠN_XÁC_NHẬN",
                content=f"Lịch hẹn {appt.code} đã tự động hủy do quá hạn xác nhận.",
                channel=NotificationChannel.IN_APP
            )
            db.add(notif)
    
    # BR-09: Confirmed -> Overdue after 24h past appointment time
    confirmed = db.query(Appointment).filter(Appointment.status == AppointmentStatus.CONFIRMED).all()
    for appt in confirmed:
        slot = appt.time_slot
        if not slot:
            continue
        slot_end = datetime.combine(slot.date, slot.end_time)
        if now - slot_end > timedelta(hours=settings.OVERDUE_HOURS):
            old = appt.status
            appt.status = AppointmentStatus.OVERDUE
            log = AppointmentLog(
                appointment_id=appt.id,
                old_status=old.value,
                new_status=AppointmentStatus.OVERDUE.value,
                performed_by="SYSTEM"
            )
            db.add(log)
    
    db.commit()
