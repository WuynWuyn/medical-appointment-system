# Website Đặt Lịch Khám Bệnh Trực Tuyến

FastAPI + Jinja2 + Tailwind CSS (theo SRS, có sẵn seeded bugs để kiểm thử)

## Yêu cầu

- Python 3.10 trở lên
- pip

## Cài đặt & chạy trên máy bạn

### 1. Giải nén

Giải nén file `appointment_booking.zip` ra bất kỳ thư mục nào.

### 2. Tạo môi trường ảo (khuyến nghị)

**Windows (PowerShell / CMD):**
```bash
cd appointment_booking
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

**macOS / Linux:**
```bash
cd appointment_booking
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Chạy server

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Mở trình duyệt: **http://localhost:8000**

Lần đầu chạy sẽ tự tạo database SQLite (`appointment.db`) và seed dữ liệu mẫu (admin, bệnh nhân, bác sĩ, khung giờ).

---

## Tài khoản demo

| Vai trò    | Email                 | Mật khẩu    |
|-----------|-----------------------|-------------|
| Admin     | admin@clinic.vn       | Admin123    |
| Bệnh nhân | patient@example.com   | Patient123  |

---

## Cấu trúc thư mục

```
appointment_booking/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   ├── auth.py
│   ├── models/models.py
│   ├── schemas/schemas.py
│   ├── services/appointment_service.py
│   ├── routers/
│   │   ├── auth.py
│   │   ├── patient.py
│   │   ├── admin.py
│   │   └── api.py
│   ├── templates/          # Jinja2 + Tailwind
│   └── static/
├── requirements.txt
└── README.md
```

## Seeded Bugs (để kiểm thử)

Xem file `danh-sach-bug-kiem-thu.docx` hoặc các comment `BUG-xx` trong code.

| Mã     | Mô tả ngắn                                      |
|--------|-------------------------------------------------|
| BUG-01 | DISPLAY_DAYS=14 vs MAX_BOOKING_DAYS=30          |
| BUG-02 | SĐT không bắt buộc khi đăng ký                  |
| BUG-04 | Không check tuổi ≥ 18                           |
| BUG-05 | Upload ảnh max 5MB (config)                     |
| BUG-06 | Hủy lịch luôn set slot AVAILABLE                |
| BUG-07 | Admin xác nhận được ca đã qua giờ               |
| BUG-08 | Cho phép INACTIVE bác sĩ dù còn lịch tương lai  |
| BUG-10 | Thiếu lock theo patient_id                      |
| BUG-11 | Race condition khi book API                     |
| BUG-12 | Validation backend yếu                          |
| BUG-13 | F5 trang success tạo lịch trùng (không PRG)     |

## API thử nghiệm bug

- `POST /api/appointments/book`  (cần đăng nhập patient, body JSON: `{"timeslot_id": 1, "reason": "..."}`)
- Dùng Postman / 2 request đồng thời để tái hiện BUG-11
