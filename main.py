from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import os
import uvicorn
from datetime import datetime, timedelta
from typing import List, Optional

import jwt
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Float, Boolean, Enum, update
from sqlalchemy.orm import declarative_base, relationship, selectinload
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.future import select
import enum

# --- КОНФИГУРАЦИЯ ---
SECRET_KEY = "super_secret_key_change_me"
ALGORITHM = "HS256"
DATABASE_URL = "sqlite+aiosqlite:///./erp_orders.db"

# --- БАЗА ДАННЫХ (SQLAlchemy ORM) ---
Base = declarative_base()

class OrderStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    IN_PURCHASING = "IN_PURCHASING"
    COMPLETED = "COMPLETED"

class UserRole(str, enum.Enum):
    INITIATOR = "INITIATOR"
    MANAGER = "MANAGER"
    PURCHASER = "PURCHASER"
    COURIER = "COURIER"

class UserModel(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String, unique=True, index=True)
    password_hash = Column(String) # В реальности храним хеш!
    name = Column(String)
    role = Column(Enum(UserRole))
    fcm_token = Column(String, nullable=True)

class OrderModel(Base):
    __tablename__ = "orders"
    id = Column(String, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    status = Column(Enum(OrderStatus), default=OrderStatus.DRAFT)
    requesting_dept_id = Column(String)
    executing_dept_id = Column(String)
    responsible_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    items = relationship("OrderItemModel", back_populates="order", cascade="all, delete-orphan")

class OrderItemModel(Base):
    __tablename__ = "order_items"
    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String, ForeignKey("orders.id"))
    material_code = Column(String, index=True)
    name = Column(String)
    unit = Column(String)
    requested_quantity = Column(Float)
    stock_balance = Column(Float)
    allow_analog = Column(Boolean, default=False)
    order = relationship("OrderModel", back_populates="items")

class StatusHistoryModel(Base):
    __tablename__ = "status_history"
    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String, ForeignKey("orders.id"))
    changed_at = Column(DateTime, default=datetime.utcnow)
    user_id = Column(Integer, ForeignKey("users.id"))
    old_status = Column(Enum(OrderStatus), nullable=True)
    new_status = Column(Enum(OrderStatus))
    comment = Column(String, nullable=True)

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

# --- Pydantic Схемы (API Контракты) ---
class LoginSchema(BaseModel):
    username: str
    password: str

class FcmTokenSchema(BaseModel):
    fcm_token: str

class OrderAssignSchema(BaseModel):
    employee_id: int

class OrderItemBase(BaseModel):
    material_code: str
    name: str
    unit: str
    requested_quantity: float
    stock_balance: float
    allow_analog: bool

class OrderCreateSchema(BaseModel):
    id: str
    requesting_dept_id: str
    executing_dept_id: str
    items: List[OrderItemBase]

class OrderResponseSchema(BaseModel):
    id: str
    created_at: datetime
    status: OrderStatus
    requesting_dept_id: str
    executing_dept_id: str
    responsible_user_id: Optional[int]
    items: List[OrderItemBase]

    class Config:
        from_attributes = True

# --- ИНИЦИАЛИЗАЦИЯ И ЗАВИСИМОСТИ ---
app = FastAPI(title="ERP Order Management API")
templates = Jinja2Templates(directory="templates")
@app.get("/app", response_class=HTMLResponse)
async def web_app(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})
# Настройка CORS для работы в онлайне
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

security = HTTPBearer()

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

def create_access_token(user_id: int):
    expire = datetime.utcnow() + timedelta(days=30)
    to_encode = {"sub": str(user_id), "exp": expire}
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user_id(credentials: HTTPAuthorizationCredentials = Depends(security)) -> int:
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        return int(payload.get("sub"))
    except Exception:
        raise HTTPException(status_code=401, detail="Неверный или просроченный токен")

@app.on_event("startup")
async def startup_event():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    # Добавим тестового пользователя, если БД пуста
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(UserModel).limit(1))
        if not result.scalars().first():
            test_user = UserModel(username="ivan", password_hash="1234", name="Иван Курьер", role=UserRole.COURIER)
            db.add(test_user)
            await db.commit()

# --- ЭНДПОИНТЫ ---
@app.post("/api/login")
async def login(credentials: LoginSchema, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(UserModel).filter_by(username=credentials.username, password_hash=credentials.password)
    )
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    
    token = create_access_token(user.id)
    return {"access_token": token, "token_type": "bearer"}

@app.post("/api/users/fcm-token")
async def update_fcm_token(
    payload: FcmTokenSchema, 
    user_id: int = Depends(get_current_user_id), 
    db: AsyncSession = Depends(get_db)
):
    await db.execute(
        update(UserModel).where(UserModel.id == user_id).values(fcm_token=payload.fcm_token)
    )
    await db.commit()
    return {"status": "success"}

@app.post("/api/orders", response_model=OrderResponseSchema)
async def create_order(order_data: OrderCreateSchema, db: AsyncSession = Depends(get_db)):
    # 1. Проверяем, нет ли уже заказа с таким ID
    result = await db.execute(select(OrderModel).filter_by(id=order_data.id))
    if result.scalars().first():
        raise HTTPException(status_code=400, detail="Заказ с таким ID уже существует")

    # 2. Создаем заказ
    new_order = OrderModel(
        id=order_data.id,
        requesting_dept_id=order_data.requesting_dept_id,
        executing_dept_id=order_data.executing_dept_id,
    )
    for item in order_data.items:
        new_order.items.append(OrderItemModel(**item.model_dump()))
    
    # 3. Сохраняем в базу
    db.add(new_order)
    await db.commit()
    
    # 4. КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: принудительно подгружаем позиции заказа (items)
    await db.refresh(new_order, attribute_names=['items'])
    
    return new_order

@app.get("/api/orders", response_model=List[OrderResponseSchema])
async def get_all_orders(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(OrderModel).options(selectinload(OrderModel.items)))
    return result.scalars().all()

@app.patch("/api/orders/{order_id}/assign", response_model=OrderResponseSchema)
async def assign_employee(
    order_id: str, 
    payload: OrderAssignSchema, 
    user_id: int = Depends(get_current_user_id), 
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(OrderModel).filter_by(id=order_id).options(selectinload(OrderModel.items)))
    order = result.scalars().first()
    if not order:
        raise HTTPException(status_code=404, detail="Заказ не найден")
        
    order.responsible_user_id = payload.employee_id
    
    audit_log = StatusHistoryModel(
        order_id=order.id, user_id=user_id, old_status=order.status, new_status=order.status,
        comment=f"Заказ назначен на сотрудника ID:{payload.employee_id}"
    )
    db.add(audit_log)
    await db.commit()
    await db.refresh(order)
    
    return order

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
