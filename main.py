from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Float, Boolean, update
from sqlalchemy.orm import declarative_base, relationship, selectinload
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.future import select
import enum
from datetime import datetime, timedelta
from typing import List, Optional
import jwt

# --- КОНФИГУРАЦИЯ ---
SECRET_KEY = "super_secret_key_change_me"
ALGORITHM = "HS256"
DATABASE_URL = "sqlite+aiosqlite:///./erp_orders.db"

# --- БАЗА ДАННЫХ ---
Base = declarative_base()

class UserModel(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String, unique=True, index=True)
    password_hash = Column(String)
    name = Column(String)
    role = Column(String)

class OrderModel(Base):
    __tablename__ = "orders"
    id = Column(String, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String, default="Черновик")
    enterprise = Column(String, nullable=True)
    requesting_dept_id = Column(String)
    executing_dept_id = Column(String)
    priority = Column(String, default="Средний")
    planned_date = Column(String, nullable=True)
    specification = Column(String, nullable=True)
    tech_spec_file = Column(String, nullable=True)
    comment = Column(String, nullable=True)
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
    stock_balance = Column(Float, default=0)
    allow_analog = Column(Boolean, default=True)
    manufacturer = Column(String, nullable=True)
    supplier = Column(String, nullable=True)
    comment = Column(String, nullable=True)
    order = relationship("OrderModel", back_populates="items")

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

# --- PYDANTIC СХЕМЫ ---
class OrderItemBase(BaseModel):
    material_code: str
    name: str
    unit: str
    requested_quantity: float
    stock_balance: float = 0
    allow_analog: bool = True
    manufacturer: Optional[str] = "-"
    supplier: Optional[str] = "-"
    comment: Optional[str] = None

class OrderCreateSchema(BaseModel):
    id: str
    enterprise: Optional[str] = "Завод №1 (Баку)"
    requesting_dept_id: str
    executing_dept_id: str
    priority: Optional[str] = "Средний"
    planned_date: Optional[str] = "Не указана"
    specification: Optional[str] = "-"
    tech_spec_file: Optional[str] = "-"
    comment: Optional[str] = None
    items: List[OrderItemBase]

# --- ПРИЛОЖЕНИЕ ---
app = FastAPI(title="ERP Order Management API")

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

@app.on_event("startup")
async def startup_event():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

# --- ВСТРОЕННЫЙ HTML ИНТЕРФЕЙС ---
HTML_CONTENT = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Управление заказами (ТЗ)</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-100 font-sans antialiased h-screen flex flex-col relative">

    <header class="bg-blue-600 text-white p-4 shadow-md flex justify-between items-center z-10">
        <h1 class="text-xl font-bold">Мои заказы</h1>
        <button id="fabAdd" class="bg-blue-700 hover:bg-blue-800 text-white px-3 py-1.5 rounded-lg font-medium text-sm flex items-center gap-1 transition shadow-sm">
            + Новый заказ
        </button>
    </header>

    <main class="flex-1 overflow-y-auto p-4" id="mainContent">
        <div class="flex items-center justify-center h-full">
            <p class="text-gray-500 text-center">Загрузка данных...</p>
        </div>
    </main>

    <!-- Модальное окно создания заказа -->
    <div id="orderModal" class="fixed inset-0 bg-black bg-opacity-50 hidden flex items-center justify-center z-50 p-4">
        <div class="bg-white p-6 rounded-xl w-full max-w-lg shadow-2xl max-h-[90vh] overflow-y-auto">
            <h2 class="text-lg font-bold mb-4 text-gray-800">Создание нового заказа</h2>
            <form id="orderForm" class="space-y-4">
                
                <div class="grid grid-cols-2 gap-3">
                    <div>
                        <label class="block text-xs font-semibold text-gray-600 mb-1">Предприятие</label>
                        <select id="enterprise" class="w-full border border-gray-300 rounded-lg p-2 text-sm bg-white">
                            <option value="Завод №1 (Баку)">Завод №1 (Баку)</option>
                            <option value="Завод №2 (Гянджа)">Завод №2 (Гянджа)</option>
                        </select>
                    </div>
                    <div>
                        <label class="block text-xs font-semibold text-gray-600 mb-1">Приоритет</label>
                        <select id="priority" class="w-full border border-gray-300 rounded-lg p-2 text-sm bg-white">
                            <option value="Средний">Средний</option>
                            <option value="Высокий">Высокий</option>
                            <option value="Низкий">Низкий</option>
                        </select>
                    </div>
                </div>

                <div class="grid grid-cols-2 gap-3">
                    <div>
                        <label class="block text-xs font-semibold text-gray-600 mb-1">Заказывающий отдел</label>
                        <input type="text" id="reqDept" required class="w-full border border-gray-300 rounded-lg p-2 text-sm" placeholder="Производство">
                    </div>
                    <div>
                        <label class="block text-xs font-semibold text-gray-600 mb-1">Исполняющий отдел</label>
                        <input type="text" id="execDept" required class="w-full border border-gray-300 rounded-lg p-2 text-sm" placeholder="Отдел закупок">
                    </div>
                </div>

                <div class="grid grid-cols-2 gap-3">
                    <div>
                        <label class="block text-xs font-semibold text-gray-600 mb-1">Плановая дата получения</label>
                        <input type="date" id="plannedDate" class="w-full border border-gray-300 rounded-lg p-2 text-sm">
                    </div>
                    <div>
                        <label class="block text-xs font-semibold text-gray-600 mb-1">Спецификация</label>
                        <input type="text" id="specification" class="w-full border border-gray-300 rounded-lg p-2 text-sm" placeholder="№ спецификации">
                    </div>
                </div>

                <div class="grid grid-cols-2 gap-3">
                    <div>
                        <label class="block text-xs font-semibold text-gray-600 mb-1">Техническое задание (ТЗ)</label>
                        <input type="file" id="techSpecFile" class="w-full border border-gray-200 rounded-lg p-1 text-xs bg-white text-gray-500">
                    </div>
                    <div>
                        <label class="block text-xs font-semibold text-gray-600 mb-1">Общий комментарий</label>
                        <input type="text" id="orderComment" class="w-full border border-gray-300 rounded-lg p-2 text-sm" placeholder="Примечания...">
                    </div>
                </div>
                
                <hr class="my-3 border-gray-200">
                <h3 class="font-bold text-sm text-gray-700">Позиция материала</h3>
                
                <div class="grid grid-cols-3 gap-2">
                    <div class="col-span-1">
                        <label class="block text-xs font-semibold text-gray-600 mb-1">Код материала</label>
                        <input type="text" id="itemCode" required class="w-full border border-gray-300 rounded-lg p-2 text-sm" placeholder="MAT-001">
                    </div>
                    <div class="col-span-2">
                        <label class="block text-xs font-semibold text-gray-600 mb-1">Наименование</label>
                        <input type="text" id="itemName" required class="w-full border border-gray-300 rounded-lg p-2 text-sm" placeholder="Подшипник">
                    </div>
                </div>

                <div class="grid grid-cols-3 gap-2">
                    <div>
                        <label class="block text-xs font-semibold text-gray-600 mb-1">Количество</label>
                        <input type="number" id="itemQty" required min="1" class="w-full border border-gray-300 rounded-lg p-2 text-sm" value="1">
                    </div>
                    <div>
                        <label class="block text-xs font-semibold text-gray-600 mb-1">Ед. изм.</label>
                        <input type="text" id="itemUnit" required class="w-full border border-gray-300 rounded-lg p-2 text-sm" value="шт">
                    </div>
                    <div>
                        <label class="block text-xs font-semibold text-gray-600 mb-1">Аналог (Да/Нет)</label>
                        <select id="allowAnalog" class="w-full border border-gray-300 rounded-lg p-2 text-sm bg-white">
                            <option value="true">Да</option>
                            <option value="false">Нет</option>
                        </select>
                    </div>
                </div>

                <div class="grid grid-cols-2 gap-2">
                    <div>
                        <label class="block text-xs font-semibold text-gray-600 mb-1">Производитель</label>
                        <input type="text" id="manufacturer" class="w-full border border-gray-300 rounded-lg p-2 text-sm" placeholder="SKF / Bosch">
                    </div>
                    <div>
                        <label class="block text-xs font-semibold text-gray-600 mb-1">Поставщик (если есть)</label>
                        <input type="text" id="supplier" class="w-full border border-gray-300 rounded-lg p-2 text-sm" placeholder="ООО «Поставка»">
                    </div>
                </div>
                
                <div class="flex justify-end space-x-2 mt-5 pt-3 border-t border-gray-200">
                    <button type="button" id="closeModalBtn" class="px-4 py-2 text-sm font-medium text-gray-600 bg-gray-100 rounded-lg hover:bg-gray-200">Отмена</button>
                    <button type="submit" class="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700">Создать заказ</button>
                </div>
            </form>
        </div>
    </div>

    <!-- Модальное окно детализации заказа -->
    <div id="detailModal" class="fixed inset-0 bg-black bg-opacity-50 hidden flex items-center justify-center z-50 p-4">
        <div class="bg-white p-6 rounded-xl w-full max-w-lg shadow-2xl max-h-[90vh] overflow-y-auto">
            <div class="flex justify-between items-center mb-4 border-b pb-2">
                <h2 id="detModalTitle" class="text-lg font-bold text-gray-800">Детали заказа</h2>
                <button onclick="closeDetailModal()" class="text-gray-400 hover:text-gray-600 font-bold text-lg">&times;</button>
            </div>
            <div id="detModalBody" class="space-y-4 text-sm text-gray-700">
                <!-- Сюда динамически подгружается инфо -->
            </div>
            <div class="flex justify-end mt-6 pt-3 border-t">
                <button onclick="closeDetailModal()" class="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700">Закрыть</button>
            </div>
        </div>
    </div>

    <script>
        const modal = document.getElementById('orderModal');
        const fabAdd = document.getElementById('fabAdd');
        const closeModalBtn = document.getElementById('closeModalBtn');
        const orderForm = document.getElementById('orderForm');

        fabAdd.addEventListener('click', () => modal.classList.remove('hidden'));
        closeModalBtn.addEventListener('click', () => {
            modal.classList.add('hidden');
            orderForm.reset();
        });

        function closeDetailModal() {
            document.getElementById('detailModal').classList.add('hidden');
        }

        // Отправка формы нового заказа
        orderForm.addEventListener('submit', async (e) => {
            e.preventDefault(); 
            const fileInput = document.getElementById('techSpecFile');
            const fileName = fileInput.files.length > 0 ? fileInput.files[0].name : 'Не прикреплен';

            const newOrder = {
                id: Math.floor(Math.random() * 90000 + 10000).toString(), 
                enterprise: document.getElementById('enterprise').value,
                requesting_dept_id: document.getElementById('reqDept').value,
                executing_dept_id: document.getElementById('execDept').value,
                priority: document.getElementById('priority').value,
                planned_date: document.getElementById('plannedDate').value || 'Не указана',
                specification: document.getElementById('specification').value || '-',
                tech_spec_file: fileName,
                comment: document.getElementById('orderComment').value || '',
                items: [
                    {
                        material_code: document.getElementById('itemCode').value,
                        name: document.getElementById('itemName').value,
                        unit: document.getElementById('itemUnit').value,
                        requested_quantity: parseFloat(document.getElementById('itemQty').value),
                        stock_balance: 0,
                        allow_analog: document.getElementById('allowAnalog').value === 'true',
                        manufacturer: document.getElementById('manufacturer').value || '-',
                        supplier: document.getElementById('supplier').value || '-'
                    }
                ]
            };

            try {
                const response = await fetch('/api/orders', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(newOrder)
                });

                if (response.ok) {
                    modal.classList.add('hidden'); 
                    orderForm.reset();             
                    loadApp();                     
                } else {
                    alert('Ошибка при создании заказа на сервере');
                }
            } catch (error) {
                alert('Ошибка сети.');
            }
        });

        // Загрузка и рендеринг списка заказов
        async function loadApp() {
            const main = document.getElementById('mainContent');
            try {
                const response = await fetch('/api/orders');
                if (!response.ok) throw new Error('Ошибка сети');
                
                const orders = await response.json();
                if (!orders || orders.length === 0) {
                    main.innerHTML = '<div class="flex items-center justify-center h-full"><p class="text-gray-500">У вас пока нет заказов</p></div>';
                    return;
                }
                
                let html = '<div class="space-y-4 max-w-2xl mx-auto">';
                orders.forEach(order => {
                    let priorityColor = 'bg-gray-100 text-gray-700';
                    if (order.priority === 'Высокий') priorityColor = 'bg-red-100 text-red-700';
                    if (order.priority === 'Средний') priorityColor = 'bg-amber-100 text-amber-700';

                    let itemsHtml = '';
                    if (order.items && order.items.length > 0) {
                        itemsHtml = '<div class="mt-3 pt-3 border-t border-gray-100 space-y-2">';
                        order.items.forEach(item => {
                            let analogText = item.allow_analog ? 'Аналог: Да' : 'Аналог: Нет';
                            itemsHtml += `
                                <div class="bg-gray-50 p-2.5 rounded-lg text-sm">
                                    <div class="flex justify-between font-medium text-gray-900">
                                        <span>${item.name} (${item.material_code})</span>
                                        <span>${item.requested_quantity} ${item.unit}</span>
                                    </div>
                                    <div class="text-xs text-gray-500 mt-1 flex gap-3 flex-wrap">
                                        <span>Производитель: <b>${item.manufacturer || '-'}</b></span>
                                        <span>Поставщик: <b>${item.supplier || '-'}</b></span>
                                        <span class="text-blue-600">${analogText}</span>
                                    </div>
                                </div>
                            `;
                        });
                        itemsHtml += '</div>';
                    }

                    // Карточка заказа кликабельна
                    html += `
                        <div onclick='openDetail(${JSON.stringify(order)})' class="bg-white p-4 rounded-xl shadow-sm border border-gray-200 hover:border-blue-400 cursor-pointer transition">
                            <div class="flex justify-between items-start mb-2">
                                <div>
                                    <div class="flex items-center gap-2 flex-wrap">
                                        <h3 class="font-bold text-gray-900">Заказ #${order.id || '?'}</h3>
                                        <span class="text-xs font-semibold px-2 py-0.5 rounded ${priorityColor}">Приоритет: ${order.priority || 'Средний'}</span>
                                    </div>
                                    <p class="text-xs text-gray-500 mt-1">🏭 ${order.enterprise || 'Завод'} | ${order.requesting_dept_id} ➔ ${order.executing_dept_id}</p>
                                </div>
                                <span class="text-xs font-bold px-2.5 py-1 rounded-full bg-blue-100 text-blue-700">${order.status || 'Черновик'}</span>
                            </div>
                            
                            <div class="text-xs text-gray-600 mb-1 flex gap-4 flex-wrap">
                                ${order.planned_date ? `<span>📅 План: <b>${order.planned_date}</b></span>` : ''}
                                ${order.specification ? `<span>📋 Спецификация: <b>${order.specification}</b></span>` : ''}
                                ${order.tech_spec_file ? `<span>📎 ТЗ: <b class="text-blue-600">${order.tech_spec_file}</b></span>` : ''}
                            </div>
                            
                            ${order.comment ? `<p class="text-xs text-gray-500 italic mb-2">💬 "${order.comment}"</p>` : ''}
                            ${itemsHtml}
                        </div>
                    `;
                });
                html += '</div>';
                main.innerHTML = html;
            } catch (error) {
                main.innerHTML = '<div class="flex items-center justify-center h-full"><p class="text-red-500">Ошибка подключения к серверу</p></div>';
            }
        }

        // Открытие детальной информации по клику на карточку
        function openDetail(order) {
            document.getElementById('detModalTitle').innerText = `Детали заказа #${order.id}`;
            
            let itemsDetails = '';
            if (order.items) {
                order.items.forEach(item => {
                    itemsDetails += `
                        <div class="bg-gray-50 p-3 rounded-lg border border-gray-200 space-y-1">
                            <div><b>Наименование:</b> ${item.name} (${item.material_code})</div>
                            <div><b>Количество:</b> ${item.requested_quantity} ${item.unit}</div>
                            <div><b>Производитель:</b> ${item.manufacturer || '-'}</div>
                            <div><b>Поставщик:</b> ${item.supplier || '-'}</div>
                            <div><b>Допуск аналога:</b> ${item.allow_analog ? 'Да' : 'Нет'}</div>
                        </div>
                    `;
                });
            }

            // Кнопка загрузки/скачивания ТЗ
            let downloadBtnHtml = order.tech_spec_file && order.tech_spec_file !== '-' 
                ? `<a href="#" onclick="alert('Скачивание файла: ${order.tech_spec_file}'); return false;" class="inline-flex items-center gap-1.5 px-3 py-1.5 bg-blue-50 text-blue-700 rounded-lg text-xs font-semibold hover:bg-blue-100 transition">📥 Скачать ТЗ (${order.tech_spec_file})</a>`
                : '<span class="text-gray-400 text-xs">Файл ТЗ не прикреплен</span>';

            document.getElementById('detModalBody').innerHTML = `
                <div class="space-y-2">
                    <p><b>Статус:</b> <span class="px-2 py-0.5 bg-blue-100 text-blue-700 rounded font-semibold">${order.status}</span></p>
                    <p><b>Предприятие:</b> ${order.enterprise || '-'}</p>
                    <p><b>Направление:</b> ${order.requesting_dept_id} ➔ ${order.executing_dept_id}</p>
                    <p><b>Приоритет:</b> ${order.priority}</p>
                    <p><b>Плановая дата:</b> ${order.planned_date}</p>
                    <p><b>Спецификация:</b> ${order.specification || '-'}</p>
                    <p><b>Дата создания:</b> ${new Date(order.created_at).toLocaleString()}</p>
                    <div class="pt-2">
                        <label class="block text-xs font-semibold text-gray-600 mb-1">Техническое задание:</label>
                        ${downloadBtnHtml}
                    </div>
                    ${order.comment ? `<p><b>Комментарий:</b> ${order.comment}</p>` : ''}
                    <hr class="my-2">
                    <h4 class="font-bold text-gray-800">Позиция материала:</h4>
                    ${itemsDetails}
                </div>
            `;
            document.getElementById('detailModal').classList.remove('hidden');
        }

        loadApp();
    </script>
</body>
</html>
"""

@app.get("/app", response_class=HTMLResponse)
async def web_app():
    return HTMLResponse(content=HTML_CONTENT)

# --- API ЭНДПОИНТЫ ---
@app.post("/api/orders", response_model=dict)
async def create_order(order_data: OrderCreateSchema, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(OrderModel).filter_by(id=order_data.id))
    if result.scalars().first():
        raise HTTPException(status_code=400, detail="Заказ с таким ID уже существует")

    new_order = OrderModel(
        id=order_data.id,
        enterprise=order_data.enterprise,
        requesting_dept_id=order_data.requesting_dept_id,
        executing_dept_id=order_data.executing_dept_id,
        priority=order_data.priority,
        planned_date=order_data.planned_date,
        specification=order_data.specification,
        tech_spec_file=order_data.tech_spec_file,
        comment=order_data.comment,
        status="Черновик"
    )
    for item in order_data.items:
        new_order.items.append(OrderItemModel(**item.model_dump()))
    
    db.add(new_order)
    await db.commit()
    await db.refresh(new_order, attribute_names=['items'])
    
    return {"status": "success", "id": new_order.id}

@app.get("/api/orders", response_model=List[dict])
async def get_all_orders(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(OrderModel).options(selectinload(OrderModel.items)))
    orders = result.scalars().all()
    
    response_data = []
    for order in orders:
        response_data.append({
            "id": order.id,
            "created_at": order.created_at.isoformat(),
            "status": order.status,
            "enterprise": order.enterprise,
            "requesting_dept_id": order.requesting_dept_id,
            "executing_dept_id": order.executing_dept_id,
            "priority": order.priority,
            "planned_date": order.planned_date,
            "specification": order.specification,
            "tech_spec_file": order.tech_spec_file,
            "comment": order.comment,
            "items": [
                {
                    "material_code": item.material_code,
                    "name": item.name,
                    "unit": item.unit,
                    "requested_quantity": item.requested_quantity,
                    "stock_balance": item.stock_balance,
                    "allow_analog": item.allow_analog,
                    "manufacturer": item.manufacturer,
                    "supplier": item.supplier,
                    "comment": item.comment
                } for item in order.items
            ]
        })
    return response_data
