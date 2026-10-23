from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    APP_NAME: str = "Website Đặt Lịch Khám Bệnh"
    SECRET_KEY: str = "super-secret-key-for-appointment-booking-2026-change-in-prod"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours
    DATABASE_URL: str = "sqlite:///./appointment.db"
    
    # Business rules (configurable)
    MIN_BOOKING_HOURS: int = 2
    MAX_BOOKING_DAYS: int = 30  # BR-03
    DISPLAY_DAYS: int = 14  # BUG-01: intentional mismatch with MAX_BOOKING_DAYS
    MAX_ACTIVE_APPOINTMENTS: int = 5
    MIN_CANCEL_HOURS: int = 2  # BR-05
    AUTO_EXPIRE_CONFIRM_HOURS: int = 1  # BR-11
    OVERDUE_HOURS: int = 24  # BR-09
    
    # Upload
    MAX_UPLOAD_SIZE_MB: int = 5  # BUG-05: FR says 5, UC says 2
    UPLOAD_DIR: str = "app/static/uploads"
    
    class Config:
        env_file = ".env"

@lru_cache()
def get_settings():
    return Settings()
