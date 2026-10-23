from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from contextlib import asynccontextmanager
from apscheduler.schedulers.background import BackgroundScheduler
from app.database import engine, Base, SessionLocal
from app.models.models import User, Specialty, Doctor, TimeSlot, UserRole, DoctorStatus, SlotStatus
from app.auth import get_password_hash
from app.routers import auth, patient, admin, api
from app.services.appointment_service import run_background_jobs
from app.config import get_settings
from datetime import date, time, timedelta, datetime
import os

settings = get_settings()

def seed_data():
    db = SessionLocal()
    try:
        if db.query(User).filter(User.role == UserRole.ADMIN).first():
            return  # already seeded
        
        # Admin
        admin = User(
            full_name="Admin Hệ thống",
            email="admin@clinic.vn",
            phone="0901000000",
            hashed_password=get_password_hash("Admin123"),
            role=UserRole.ADMIN
        )
        db.add(admin)
        
        # Patient demo
        patient = User(
            full_name="Nguyễn Văn An",
            email="patient@example.com",
            phone="0912345678",
            hashed_password=get_password_hash("Patient123"),
            role=UserRole.PATIENT,
            date_of_birth=date(1995, 8, 15),
            gender="Nam"
        )
        db.add(patient)
        
        # Specialties
        specs = [
            Specialty(name="Nội tổng quát", description="Khám nội khoa"),
            Specialty(name="Nhi khoa", description="Khám trẻ em"),
            Specialty(name="Da liễu", description="Da và thẩm mỹ"),
            Specialty(name="Tim mạch", description="Tim và mạch máu"),
            Specialty(name="Tai mũi họng", description="TMH"),
        ]
        for s in specs:
            db.add(s)
        db.flush()
        
        # Doctors
        doctors_data = [
            ("BS. Trần Thị Bình", 1, "ThS", 12, 300000, "tranbinh@clinic.vn", "0911111111"),
            ("BS. Lê Văn Cường", 2, "BSCKI", 8, 250000, "lecuong@clinic.vn", "0922222222"),
            ("BS. Phạm Thu Dung", 3, "ThS", 15, 400000, "phamdung@clinic.vn", "0933333333"),
            ("BS. Hoàng Minh Đức", 4, "PGS.TS", 20, 500000, "hoangduc@clinic.vn", "0944444444"),
            ("BS. Nguyễn Thị Em", 5, "BS", 5, 200000, "nguyenem@clinic.vn", "0955555555"),
        ]
        for name, sid, deg, exp, fee, email, phone in doctors_data:
            d = Doctor(
                full_name=name, specialty_id=sid, degree=deg,
                experience_years=exp, consultation_fee=fee,
                email=email, phone=phone, bio=f"Bác sĩ chuyên khoa với {exp} năm kinh nghiệm."
            )
            db.add(d)
        db.flush()
        
        # Generate slots for next 14 days (matching DISPLAY_DAYS bug)
        doctors = db.query(Doctor).all()
        today = date.today()
        for d in doctors:
            for day_offset in range(1, 15):  # tomorrow to +14
                d_date = today + timedelta(days=day_offset)
                if d_date.weekday() >= 5:  # skip weekend for simplicity
                    continue
                for hour in range(8, 12):  # morning slots
                    for m in [0, 30]:
                        st = time(hour, m)
                        et = time(hour, m + 30) if m == 0 else time(hour + 1, 0)
                        slot = TimeSlot(
                            doctor_id=d.id, date=d_date,
                            start_time=st, end_time=et, status=SlotStatus.AVAILABLE
                        )
                        db.add(slot)
                for hour in range(13, 17):
                    for m in [0, 30]:
                        st = time(hour, m)
                        et = time(hour, m + 30) if m == 0 else time(hour + 1, 0)
                        slot = TimeSlot(
                            doctor_id=d.id, date=d_date,
                            start_time=st, end_time=et, status=SlotStatus.AVAILABLE
                        )
                        db.add(slot)
        
        db.commit()
        print("Seed data created successfully.")
    except Exception as e:
        db.rollback()
        print(f"Seed error: {e}")
    finally:
        db.close()

scheduler = BackgroundScheduler()

def scheduled_jobs():
    db = SessionLocal()
    try:
        run_background_jobs(db)
    finally:
        db.close()

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    seed_data()
    scheduler.add_job(scheduled_jobs, "interval", minutes=5)
    scheduler.start()
    yield
    scheduler.shutdown()

app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(auth.router)
app.include_router(patient.router)
app.include_router(admin.router)
app.include_router(api.router)

@app.get("/health")
def health():
    return {"status": "ok"}
