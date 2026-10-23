from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, Enum, Float, Date, Time, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from app.database import Base

class UserRole(str, enum.Enum):
    PATIENT = "PATIENT"
    ADMIN = "ADMIN"

class UserStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    LOCKED = "LOCKED"
    INACTIVE = "INACTIVE"

class DoctorStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"

class SlotStatus(str, enum.Enum):
    AVAILABLE = "AVAILABLE"
    BOOKED = "BOOKED"
    BLOCKED = "BLOCKED"

class AppointmentStatus(str, enum.Enum):
    PENDING = "Chờ xác nhận"
    CONFIRMED = "Đã xác nhận"
    CANCELLED = "Đã hủy"  # BUG-03: consistent with FR, but state diagram says "Đã hủy bỏ"
    COMPLETED = "Đã hoàn thành"
    NO_SHOW = "Vắng mặt"
    OVERDUE = "Quá hạn"

class NotificationChannel(str, enum.Enum):
    IN_APP = "IN_APP"
    EMAIL = "EMAIL"

class NotificationStatus(str, enum.Enum):
    SUCCESS = "THÀNH_CÔNG"
    FAILED = "THẤT_BẠI"

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(100), nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    phone = Column(String(15), unique=True, index=True, nullable=True)  # BUG-02: not required in register form
    hashed_password = Column(String(255), nullable=False)
    date_of_birth = Column(Date, nullable=True)
    gender = Column(String(10), nullable=True)
    role = Column(Enum(UserRole), default=UserRole.PATIENT)
    status = Column(Enum(UserStatus), default=UserStatus.ACTIVE)
    failed_login_attempts = Column(Integer, default=0)
    locked_until = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    appointments = relationship("Appointment", back_populates="patient", foreign_keys="Appointment.patient_id")
    notifications = relationship("Notification", back_populates="user")

class Specialty(Base):
    __tablename__ = "specialties"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    
    doctors = relationship("Doctor", back_populates="specialty")

class Doctor(Base):
    __tablename__ = "doctors"
    
    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(100), nullable=False)
    specialty_id = Column(Integer, ForeignKey("specialties.id"), nullable=False)
    degree = Column(String(50), nullable=True)  # học vị
    experience_years = Column(Integer, default=0)
    bio = Column(Text, nullable=True)
    consultation_fee = Column(Integer, default=0)  # VND
    avatar = Column(String(255), nullable=True)
    email = Column(String(100), unique=True, nullable=False)
    phone = Column(String(15), nullable=False)
    status = Column(Enum(DoctorStatus), default=DoctorStatus.ACTIVE)
    is_deleted = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    specialty = relationship("Specialty", back_populates="doctors")
    time_slots = relationship("TimeSlot", back_populates="doctor")
    appointments = relationship("Appointment", back_populates="doctor")

class TimeSlot(Base):
    __tablename__ = "time_slots"
    
    id = Column(Integer, primary_key=True, index=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    date = Column(Date, nullable=False)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    status = Column(Enum(SlotStatus), default=SlotStatus.AVAILABLE)
    
    __table_args__ = (
        UniqueConstraint('doctor_id', 'date', 'start_time', name='uq_doctor_slot'),
    )
    
    doctor = relationship("Doctor", back_populates="time_slots")
    appointment = relationship("Appointment", back_populates="time_slot", uselist=False)

class Appointment(Base):
    __tablename__ = "appointments"
    
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(30), unique=True, index=True, nullable=False)  # LH-YYYYMMDD-XXXX
    patient_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    timeslot_id = Column(Integer, ForeignKey("time_slots.id"), nullable=False)
    reason = Column(Text, nullable=False)
    status = Column(Enum(AppointmentStatus), default=AppointmentStatus.PENDING)
    cancel_reason = Column(Text, nullable=True)
    cancelled_by = Column(String(50), nullable=True)  # PATIENT / ADMIN / SYSTEM
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    patient = relationship("User", back_populates="appointments", foreign_keys=[patient_id])
    doctor = relationship("Doctor", back_populates="appointments")
    time_slot = relationship("TimeSlot", back_populates="appointment")
    logs = relationship("AppointmentLog", back_populates="appointment")

class AppointmentLog(Base):
    __tablename__ = "appointment_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    appointment_id = Column(Integer, ForeignKey("appointments.id"), nullable=False)
    old_status = Column(String(50), nullable=True)
    new_status = Column(String(50), nullable=False)
    performed_by = Column(String(100), nullable=False)  # user id or "SYSTEM"
    created_at = Column(DateTime, default=datetime.utcnow)
    
    appointment = relationship("Appointment", back_populates="logs")

class Notification(Base):
    __tablename__ = "notifications"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    appointment_id = Column(Integer, ForeignKey("appointments.id"), nullable=True)
    type = Column(String(50), nullable=False)
    content = Column(Text, nullable=False)
    channel = Column(Enum(NotificationChannel), default=NotificationChannel.IN_APP)
    send_status = Column(Enum(NotificationStatus), default=NotificationStatus.SUCCESS)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="notifications")
