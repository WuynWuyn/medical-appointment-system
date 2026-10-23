from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional, List
from datetime import date, time, datetime
from app.models.models import UserRole, DoctorStatus, SlotStatus, AppointmentStatus

# ========== Auth ==========
class UserRegister(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=50)
    email: EmailStr
    # BUG-02: phone is NOT required in form (but table 4.4 requires it)
    phone: Optional[str] = None
    password: str = Field(..., min_length=8, max_length=64)
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None

    @field_validator("password")
    @classmethod
    def password_strength(cls, v):
        if not any(c.isalpha() for c in v) or not any(c.isdigit() for c in v):
            raise ValueError("Mật khẩu phải có ít nhất 1 chữ cái và 1 chữ số")
        return v

    # BUG-04: No age validation (SRS has conflict: table says >=18 but Nhi khoa needs children)
    # Intentionally NO min age check here

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None

class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8, max_length=64)

# ========== Doctor ==========
class SpecialtyCreate(BaseModel):
    name: str
    description: Optional[str] = None

class DoctorCreate(BaseModel):
    full_name: str
    specialty_id: int
    degree: Optional[str] = None
    experience_years: int = 0
    bio: Optional[str] = None
    consultation_fee: int = 0
    email: EmailStr
    phone: str

class DoctorUpdate(BaseModel):
    full_name: Optional[str] = None
    specialty_id: Optional[int] = None
    degree: Optional[str] = None
    experience_years: Optional[int] = None
    bio: Optional[str] = None
    consultation_fee: Optional[int] = None
    phone: Optional[str] = None
    status: Optional[DoctorStatus] = None

# ========== TimeSlot ==========
class TimeSlotCreate(BaseModel):
    doctor_id: int
    date: date
    start_time: time
    end_time: time

class BulkSlotCreate(BaseModel):
    doctor_id: int
    start_date: date
    end_date: date
    start_hour: int = 8
    end_hour: int = 17
    slot_minutes: int = 30
    weekdays: Optional[List[int]] = None  # 0=Mon ... 6=Sun

# ========== Appointment ==========
class AppointmentCreate(BaseModel):
    timeslot_id: int
    reason: str = Field(..., min_length=1, max_length=500)

class AppointmentCancel(BaseModel):
    reason: Optional[str] = Field(None, max_length=300)

class AppointmentAdminAction(BaseModel):
    action: str  # confirm / cancel / complete / no_show
    reason: Optional[str] = None
