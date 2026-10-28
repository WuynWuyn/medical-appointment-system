from datetime import datetime, timedelta
import token
from fastapi import APIRouter, Depends, HTTPException, Request, Response, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from urllib.parse import urlsplit
from app.database import get_db
from app.models.models import User, UserRole, UserStatus
from app.auth import get_password_hash, verify_password, create_access_token, get_current_user
from app.config import get_settings
from app.schemas.schemas import UserRegister
import re

router = APIRouter(prefix="/auth", tags=["auth"])
templates = Jinja2Templates(directory="app/templates")
settings = get_settings()

def validate_phone(phone: str) -> bool:
    if not phone:
        return True  # BUG-02: phone optional
    # Normalize
    phone = re.sub(r'[\s\.\-\+]', '', phone)
    if phone.startswith("84"):
        phone = "0" + phone[2:]
    return bool(re.match(r'^0[35789]\d{8}$', phone))

@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse("auth/register.html", {"request": request})

@router.post("/register")
async def register(
    request: Request,
    full_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    phone: str = Form(None),  # BUG-02: optional
    date_of_birth: str = Form(None),
    gender: str = Form(None),
    db: Session = Depends(get_db)
):
    errors = []
    if len(full_name) < 2 or len(full_name) > 50:
        errors.append("Họ tên phải từ 2-50 ký tự")
    
    if db.query(User).filter(User.email == email.lower()).first():
        errors.append("Email đã được sử dụng")
    
    if phone and not validate_phone(phone):
        errors.append("Số điện thoại không hợp lệ")
    
    if phone and db.query(User).filter(User.phone == phone).first():
        errors.append("Số điện thoại đã được sử dụng")
    
    if len(password) < 8 or not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
        errors.append("Mật khẩu tối thiểu 8 ký tự, có chữ và số")
    
    # BUG-04: No age check for >=18 even though table 4.4 implies it for some contexts
    dob = None
    if date_of_birth:
        try:
            from datetime import datetime as dt
            dob = dt.strptime(date_of_birth, "%Y-%m-%d").date()
            if dob > datetime.now().date():
                errors.append("Ngày sinh không hợp lệ")
        except:
            errors.append("Ngày sinh không đúng định dạng")
    
    if errors:
        return templates.TemplateResponse("auth/register.html", {
            "request": request, "errors": errors,
            "form": {"full_name": full_name, "email": email, "phone": phone or ""}
        })
    
    user = User(
        full_name=full_name.strip(),
        email=email.lower().strip(),
        phone=phone.strip() if phone else None,
        hashed_password=get_password_hash(password),
        date_of_birth=dob,
        gender=gender,
        role=UserRole.PATIENT
    )
    db.add(user)
    db.commit()
    return RedirectResponse("/auth/login?registered=1", status_code=303)

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("auth/login.html", {
        "request": request,
        "registered": request.query_params.get("registered"),
        "next_url": request.query_params.get("next")
    })

@router.post("/login")
async def login(
    request: Request,
    response: Response,
    email: str = Form(...),
    password: str = Form(...),
    next_url: str = Form(None, alias="next"),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.email == email.lower()).first()
    if not user:
        return templates.TemplateResponse("auth/login.html", {
            "request": request, "error": "Email hoặc mật khẩu không đúng",
            "next_url": next_url
        })
    
    # Lock check
    if user.status == UserStatus.LOCKED and user.locked_until and user.locked_until > datetime.utcnow():
        return templates.TemplateResponse("auth/login.html", {
            "request": request, "error": "Tài khoản bị khóa tạm thời. Thử lại sau.",
            "next_url": next_url
        })
    
    if not verify_password(password, user.hashed_password):
        user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
        if user.failed_login_attempts >= 5:
            user.status = UserStatus.LOCKED
            user.locked_until = datetime.utcnow() + timedelta(minutes=15)
        db.commit()
        return templates.TemplateResponse("auth/login.html", {
            "request": request, "error": "Email hoặc mật khẩu không đúng",
            "next_url": next_url
        })
    
    user.failed_login_attempts = 0
    user.status = UserStatus.ACTIVE
    user.locked_until = None
    db.commit()
    
    token = create_access_token({"sub": user.id, "role": getattr(user.role, "value", str(user.role))})
    role_value = getattr(user.role, "value", str(user.role))
    redirect_url = "/admin" if role_value == "ADMIN" else "/my-appointments"
    if role_value != "ADMIN" and next_url:
        parsed_next = urlsplit(next_url)
        if (
            parsed_next.path.startswith("/")
            and not parsed_next.path.startswith("//")
            and not parsed_next.netloc
            and not parsed_next.scheme
            and "\\" not in next_url
        ):
            redirect_url = next_url
    resp = RedirectResponse(redirect_url, status_code=303)
    resp.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        max_age=86400,
        samesite="lax",
        path="/"
        )
    return resp

@router.get("/logout")
async def logout():
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie("access_token")
    return resp
