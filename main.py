from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Float, Boolean, update, delete
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
    
    # ПОЛЯ ДЛЯ ДАННЫХ ОТ ПОСТАВЩИКА
    supplier_name = Column(String, nullable=True)
    contract_number = Column(String, nullable=True)
    contract_date = Column(String, nullable=True)
    currency = Column(String, nullable=True)
    incoterms = Column(String, nullable=True)
    ordered_quantity = Column(Float, nullable=True)
    unit_price = Column(Float, nullable=True)
    total_amount = Column(Float, nullable=True)
    
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

class OrderStatusUpdateSchema(BaseModel):
    status: str
    reject_comment: Optional[str] = None
    supplier_name: Optional[str] = None
    contract_number: Optional[str] = None
    contract_date: Optional[str] = None
    currency: Optional[str] = None
    incoterms: Optional[str] = None
    ordered_quantity: Optional[float] = None
    unit_price: Optional[float] = None
    total_amount: Optional[float] = None

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

    <!-- Модальное окно создания / редактирования заказа -->
    <div id="orderModal" class="fixed inset-0 bg-black bg-opacity-50 hidden flex items-center justify-center z-50 p-4">
        <div class="bg-white p-6 rounded-xl w-full max-w-lg shadow-2xl max-h-[90vh] overflow-y-auto">
            <h2 id="orderModalTitle" class="text-lg font-bold mb-4 text-gray-800">Создание нового заказа</h2>
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
                        
                        <!-- Блок удаления текущего файла при редактировании -->
                        <div id="currentFileBox" class="hidden mb-2 bg-blue-50 text-blue-700 text-xs px-2 py-1.5 rounded flex justify-between items-center border border-blue-100">
                            <span id="currentFileName" class="truncate max-w-[120px] font-medium">Файл.docx</span>
                            <button type="button" onclick="removeCurrentFile()" class="text-red-500 hover:text-red-700 font-bold ml-2" title="Удалить прикрепленный файл">✕ Удалить</button>
                        </div>
                        
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
                    <button type="submit" id="submitBtn" class="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700">Создать заказ</button>
                </div>
            </form>
        </div>
    </div>

    <!-- Модальное окно детализации заказа -->
    <div id="detailModal" class="fixed inset-0 bg-black bg-opacity-50 hidden flex items-center justify-center z-50 p-4">
        <div class="bg-white p-6 rounded-xl w-full max-w-lg shadow-2xl max-h-[95vh] overflow-y-auto">
            <div class="flex justify-between items-center mb-4 border-b pb-2">
                <h2 id="detModalTitle" class="text-lg font-bold text-gray-800">Детали заказа</h2>
                <button onclick="closeDetailModal()" class="text-gray-400 hover:text-gray-600 font-bold text-lg">&times;</button>
            </div>
            <div id="detModalBody" class="space-y-4 text-sm text-gray-700">
                <!-- Контент детализации -->
            </div>
            <div id="detModalFooter" class="mt-6 pt-3 border-t flex flex-col gap-3">
                <!-- Кнопки статуса и формы -->
            </div>
        </div>
    </div>

    <script>
        let ordersCache = [];
        let editingOrderId = null; // Хранит ID заказа, если мы его редактируем
        let existingFileName = null; // Хранит имя файла при редактировании

        const modal = document.getElementById('orderModal');
        const fabAdd = document.getElementById('fabAdd');
        const closeModalBtn = document.getElementById('closeModalBtn');
        const orderForm = document.getElementById('orderForm');

        // Открытие формы на создание нового
        fabAdd.addEventListener('click', () => {
            editingOrderId = null;
            existingFileName = null;
            document.getElementById('orderModalTitle').innerText = 'Создание нового заказа';
            document.getElementById('submitBtn').innerText = 'Создать заказ';
            document.getElementById('currentFileBox').classList.add('hidden');
            orderForm.reset();
            modal.classList.remove('hidden');
        });

        closeModalBtn.addEventListener('click', () => {
            modal.classList.add('hidden');
            orderForm.reset();
        });

        function closeDetailModal() {
            document.getElementById('detailModal').classList.add('hidden');
        }

        // Удаление файла при редактировании
        function removeCurrentFile() {
            existingFileName = 'Не прикреплен';
            document.getElementById('currentFileBox').classList.add('hidden');
        }

        // Открытие формы на редактирование Черновика
        function openEditForm(orderId) {
            closeDetailModal(); // закрываем детали
            const order = ordersCache.find(o => o.id === orderId);
            if (!order) return;

            editingOrderId = order.id;
            document.getElementById('orderModalTitle').innerText = `Редактирование заказа #${order.id}`;
            document.getElementById('submitBtn').innerText = 'Сохранить изменения';

            // Заполняем поля старыми данными
            document.getElementById('enterprise').value = order.enterprise || 'Завод №1 (Баку)';
            document.getElementById('priority').value = order.priority || 'Средний';
            document.getElementById('reqDept').value = order.requesting_dept_id || '';
            document.getElementById('execDept').value = order.executing_dept_id || '';
            document.getElementById('plannedDate').value = order.planned_date || '';
            document.getElementById('specification').value = order.specification && order.specification !== '-' ? order.specification : '';
            
            // Очищаем комментарий от системных пометок отказа, если нужно, или просто выводим
            let cleanComment = order.comment || '';
            document.getElementById('orderComment').value = cleanComment;

            // Работа с файлом ТЗ
            existingFileName = order.tech_spec_file;
            if (existingFileName && existingFileName !== '-' && existingFileName !== 'Не прикреплен') {
                document.getElementById('currentFileName').innerText = existingFileName;
                document.getElementById('currentFileBox').classList.remove('hidden');
            } else {
                document.getElementById('currentFileBox').classList.add('hidden');
            }

            // Заполняем позицию (пока берем первую)
            if (order.items && order.items.length > 0) {
                const item = order.items[0];
                document.getElementById('itemCode').value = item.material_code || '';
                document.getElementById('itemName').value = item.name || '';
                document.getElementById('itemQty').value = item.requested_quantity || 1;
                document.getElementById('itemUnit').value = item.unit || 'шт';
                document.getElementById('allowAnalog').value = item.allow_analog ? 'true' : 'false';
                document.getElementById('manufacturer').value = item.manufacturer && item.manufacturer !== '-' ? item.manufacturer : '';
                document.getElementById('supplier').value = item.supplier && item.supplier !== '-' ? item.supplier : '';
            }

            modal.classList.remove('hidden');
        }

        // Сохранение заказа (создание ИЛИ редактирование)
        orderForm.addEventListener('submit', async (e) => {
            e.preventDefault(); 
            
            const fileInput = document.getElementById('techSpecFile');
            let finalFileName = 'Не прикреплен';
            
            // Если загружен новый файл - берем его, иначе оставляем старый (если его не удалили)
            if (fileInput.files.length > 0) {
                finalFileName = fileInput.files[0].name;
            } else if (existingFileName && existingFileName !== '-' && existingFileName !== 'Не прикреплен') {
                finalFileName = existingFileName;
            }

            const orderData = {
                id: editingOrderId ? editingOrderId : Math.floor(Math.random() * 90000 + 10000).toString(), 
                enterprise: document.getElementById('enterprise').value,
                requesting_dept_id: document.getElementById('reqDept').value,
                executing_dept_id: document.getElementById('execDept').value,
                priority: document.getElementById('priority').value,
                planned_date: document.getElementById('plannedDate').value || 'Не указана',
                specification: document.getElementById('specification').value || '-',
                tech_spec_file: finalFileName,
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

            const url = editingOrderId ? `/api/orders/${editingOrderId}` : '/api/orders';
            const method = editingOrderId ? 'PUT' : 'POST';

            try {
                const response = await fetch(url, {
                    method: method,
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(orderData)
                });
                if (response.ok) { 
                    modal.classList.add('hidden'); 
                    orderForm.reset(); 
                    loadApp(); 
                } else { 
                    alert('Ошибка при сохранении заказа на сервере'); 
                }
            } catch (error) { 
                alert('Ошибка сети'); 
            }
        });

        // Скачивание ТЗ
        function downloadTechSpec(orderId, fileName) {
            const content = `ТЕХНИЧЕСКОЕ ЗАДАНИЕ\\nСистема управления заказами материалов\\n----------------------------------------\\nЗаказ №: ${orderId}\\nПрикрепленный файл: ${fileName}\\nДата скачивания: ${new Date().toLocaleString()}\\nСтатус: Успешно выгружено из системы.`;
            const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = fileName;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        }

        // Обновление статуса
        async function changeStatus(orderId, newStatus, rejectComment = null, supplierData = {}) {
            try {
                const payload = { status: newStatus, reject_comment: rejectComment, ...supplierData };
                const response = await fetch(`/api/orders/${orderId}/status`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                if (response.ok) {
                    closeDetailModal();
                    loadApp();
                } else {
                    alert('Ошибка при смене статуса');
                }
            } catch (error) {
                alert('Ошибка сети.');
            }
        }

        function rejectOrder(orderId) {
            const commentInput = document.getElementById('rejectComment_' + orderId);
            const comment = commentInput ? commentInput.value.trim() : '';
            if (!comment) {
                alert('Пожалуйста, обязательно укажите причину отказа!');
                commentInput.focus();
                return;
            }
            changeStatus(orderId, 'Черновик', comment);
        }

        // --- ЛОГИКА ФОРМЫ ЗАКУПКИ ---
        function showSupplierForm(orderId, maxQty) {
            const footer = document.getElementById('detModalFooter');
            footer.innerHTML = `
                <div class="w-full bg-indigo-50 p-4 rounded-lg border border-indigo-200 shadow-inner">
                    <h4 class="font-bold text-indigo-800 mb-3 border-b border-indigo-200 pb-2">Оформление заказа у поставщика</h4>
                    <div class="grid grid-cols-2 gap-3 mb-4">
                        <div>
                            <label class="block text-xs font-semibold text-gray-700 mb-1">Поставщик</label>
                            <input type="text" id="supName" class="w-full border border-gray-300 rounded p-1.5 text-sm" placeholder="Название компании" required>
                        </div>
                        <div>
                            <label class="block text-xs font-semibold text-gray-700 mb-1">Номер договора</label>
                            <input type="text" id="supContract" class="w-full border border-gray-300 rounded p-1.5 text-sm" placeholder="№..." required>
                        </div>
                        <div>
                            <label class="block text-xs font-semibold text-gray-700 mb-1">Дата договора</label>
                            <input type="date" id="supDate" class="w-full border border-gray-300 rounded p-1.5 text-sm" required>
                        </div>
                        <div>
                            <label class="block text-xs font-semibold text-gray-700 mb-1">Валюта</label>
                            <select id="supCurrency" class="w-full border border-gray-300 rounded p-1.5 text-sm bg-white">
                                <option value="AZN">AZN (Манат)</option>
                                <option value="USD">USD (Доллар)</option>
                                <option value="EUR">EUR (Евро)</option>
                                <option value="RUB">RUB (Рубль)</option>
                            </select>
                        </div>
                        <div>
                            <label class="block text-xs font-semibold text-gray-700 mb-1">Инкотермс</label>
                            <select id="supInco" class="w-full border border-gray-300 rounded p-1.5 text-sm bg-white">
                                <option>EXW</option>
                                <option>FCA</option>
                                <option>CPT</option>
                                <option>CIP</option>
                                <option>DAP</option>
                                <option>DDP</option>
                            </select>
                        </div>
                        <div>
                            <label class="block text-xs font-semibold text-gray-700 mb-1">Кол-во (не больше ${maxQty})</label>
                            <input type="number" id="supQty" class="w-full border border-gray-300 rounded p-1.5 text-sm font-bold text-blue-700" value="${maxQty}" oninput="calcSum(${maxQty})" required>
                        </div>
                        <div>
                            <label class="block text-xs font-semibold text-gray-700 mb-1">Цена за единицу</label>
                            <input type="number" id="supPrice" step="0.01" class="w-full border border-gray-300 rounded p-1.5 text-sm" placeholder="0.00" oninput="calcSum(${maxQty})" required>
                        </div>
                        <div>
                            <label class="block text-xs font-semibold text-gray-700 mb-1">Итоговая сумма</label>
                            <input type="text" id="supTotal" class="w-full border border-indigo-200 bg-indigo-100 rounded p-1.5 text-sm font-bold text-indigo-900 outline-none" readonly value="0.00">
                        </div>
                    </div>
                    <div class="flex justify-end gap-2">
                        <button onclick="openDetail('${orderId}')" class="px-4 py-2 text-sm font-medium text-gray-600 bg-white border border-gray-300 rounded-lg hover:bg-gray-50">Отмена</button>
                        <button onclick="submitSupplierOrder('${orderId}')" class="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 shadow">Подтвердить закупку</button>
                    </div>
                </div>
            `;
        }

        function calcSum(maxQty) {
            const qtyInput = document.getElementById('supQty');
            let qty = parseFloat(qtyInput.value) || 0;
            if (qty > maxQty) {
                alert('Ошибка: Количество не может превышать исходный запрос (' + maxQty + ')!');
                qtyInput.value = maxQty;
                qty = maxQty;
            }
            let price = parseFloat(document.getElementById('supPrice').value) || 0;
            document.getElementById('supTotal').value = (qty * price).toFixed(2);
        }

        function submitSupplierOrder(orderId) {
            const supplierData = {
                supplier_name: document.getElementById('supName').value.trim(),
                contract_number: document.getElementById('supContract').value.trim(),
                contract_date: document.getElementById('supDate').value,
                currency: document.getElementById('supCurrency').value,
                incoterms: document.getElementById('supInco').value,
                ordered_quantity: parseFloat(document.getElementById('supQty').value) || 0,
                unit_price: parseFloat(document.getElementById('supPrice').value) || 0,
                total_amount: parseFloat(document.getElementById('supTotal').value) || 0
            };
            if (!supplierData.supplier_name || !supplierData.contract_number || !supplierData.contract_date || !supplierData.unit_price) {
                alert('Пожалуйста, заполните все обязательные поля поставщика!');
                return;
            }
            changeStatus(orderId, 'Заказан поставщику', null, supplierData);
        }

        async function loadApp() {
            const main = document.getElementById('mainContent');
            try {
                const response = await fetch('/api/orders');
                if (!response.ok) throw new Error('Ошибка сети');
                const orders = await response.json();
                ordersCache = orders;
                
                if (!orders || orders.length === 0) {
                    main.innerHTML = '<div class="flex items-center justify-center h-full"><p class="text-gray-500">У вас пока нет заказов</p></div>';
                    return;
                }
                
                let html = '<div class="space-y-4 max-w-2xl mx-auto">';
                orders.forEach(order => {
                    let priorityColor = 'bg-gray-100 text-gray-700';
                    if (order.priority === 'Высокий') priorityColor = 'bg-red-100 text-red-700';
                    if (order.priority === 'Средний') priorityColor = 'bg-amber-100 text-amber-700';

                    let statusColor = 'bg-blue-100 text-blue-700';
                    if (order.status === 'На согласовании') statusColor = 'bg-yellow-100 text-yellow-700';
                    if (order.status === 'Принят в работу') statusColor = 'bg-purple-100 text-purple-700';
                    if (order.status === 'Заказан поставщику') statusColor = 'bg-indigo-100 text-indigo-700';
                    if (order.status === 'На складе') statusColor = 'bg-orange-100 text-orange-700';
                    if (order.status === 'Выполнен') statusColor = 'bg-green-100 text-green-700';

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
                                </div>
                            `;
                        });
                        itemsHtml += '</div>';
                    }

                    html += `
                        <div onclick="openDetail('${order.id}')" class="bg-white p-4 rounded-xl shadow-sm border border-gray-200 hover:border-blue-400 cursor-pointer transition">
                            <div class="flex justify-between items-start mb-2">
                                <div>
                                    <div class="flex items-center gap-2 flex-wrap">
                                        <h3 class="font-bold text-gray-900">Заказ #${order.id || '?'}</h3>
                                        <span class="text-xs font-semibold px-2 py-0.5 rounded ${priorityColor}">Приоритет: ${order.priority || 'Средний'}</span>
                                    </div>
                                    <p class="text-xs text-gray-500 mt-1">🏭 ${order.enterprise || 'Завод'} | ${order.requesting_dept_id} ➔ ${order.executing_dept_id}</p>
                                </div>
                                <span class="text-xs font-bold px-2.5 py-1 rounded-full ${statusColor}">${order.status}</span>
                            </div>
                            <div class="text-xs text-gray-600 flex gap-4 flex-wrap mb-1">
                                ${order.planned_date ? `<span>📅 План: <b>${order.planned_date}</b></span>` : ''}
                                ${order.specification && order.specification !== '-' ? `<span>📋 Спец.: <b>${order.specification}</b></span>` : ''}
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

        function openDetail(orderId) {
            const order = ordersCache.find(o => o.id === orderId);
            if (!order) return;

            let totalRequestedQty = 0;
            if (order.items) { order.items.forEach(item => totalRequestedQty += item.requested_quantity); }

            document.getElementById('detModalTitle').innerText = `Детали заказа #${order.id}`;
            
            let statusBadge = `<span class="px-2 py-0.5 bg-blue-100 text-blue-700 rounded font-semibold">${order.status}</span>`;
            if (order.status === 'На согласовании') statusBadge = `<span class="px-2 py-0.5 bg-yellow-100 text-yellow-700 rounded font-semibold">${order.status}</span>`;
            if (order.status === 'Принят в работу') statusBadge = `<span class="px-2 py-0.5 bg-purple-100 text-purple-700 rounded font-semibold">${order.status}</span>`;
            if (order.status === 'Заказан поставщику') statusBadge = `<span class="px-2 py-0.5 bg-indigo-100 text-indigo-700 rounded font-semibold">${order.status}</span>`;
            if (order.status === 'На складе') statusBadge = `<span class="px-2 py-0.5 bg-orange-100 text-orange-700 rounded font-semibold">${order.status}</span>`;
            if (order.status === 'Выполнен') statusBadge = `<span class="px-2 py-0.5 bg-green-100 text-green-700 rounded font-semibold">${order.status}</span>`;

            let itemsDetails = '';
            if (order.items) {
                order.items.forEach(item => {
                    itemsDetails += `
                        <div class="bg-gray-50 p-3 rounded-lg border border-gray-200 space-y-1">
                            <div><b>Наименование:</b> ${item.name} (${item.material_code})</div>
                            <div><b>Количество:</b> ${item.requested_quantity} ${item.unit}</div>
                            <div><b>Производитель:</b> ${item.manufacturer || '-'}</div>
                            <div><b>Поставщик (ожидаемый):</b> ${item.supplier || '-'}</div>
                            <div><b>Допуск аналога:</b> ${item.allow_analog ? 'Да' : 'Нет'}</div>
                        </div>
                    `;
                });
            }

            let downloadBtnHtml = order.tech_spec_file && order.tech_spec_file !== '-' && order.tech_spec_file !== 'Не прикреплен'
                ? `<button onclick="downloadTechSpec('${order.id}', '${order.tech_spec_file}')" class="inline-flex items-center gap-1.5 px-3 py-1.5 bg-blue-50 text-blue-700 rounded-lg text-xs font-semibold hover:bg-blue-100 transition cursor-pointer">📥 Скачать ТЗ (${order.tech_spec_file})</button>`
                : '<span class="text-gray-400 text-xs">Файл ТЗ не прикреплен</span>';

            let supplierInfoHtml = '';
            if (order.status === 'Заказан поставщику' || order.status === 'На складе' || order.status === 'Выполнен') {
                if (order.supplier_name) {
                    supplierInfoHtml = `
                        <hr class="my-3">
                        <h4 class="font-bold text-indigo-800">Данные закупки:</h4>
                        <div class="bg-indigo-50 p-3 rounded-lg border border-indigo-200 text-sm space-y-1 mt-2">
                            <p><b>Поставщик:</b> ${order.supplier_name}</p>
                            <p><b>Договор:</b> №${order.contract_number} от ${order.contract_date}</p>
                            <p><b>Условия:</b> Инкотермс ${order.incoterms}, Валюта ${order.currency}</p>
                            <p><b>Фактически заказано:</b> <span class="text-indigo-700 font-bold">${order.ordered_quantity} шт.</span></p>
                            <p><b>Цена за ед.:</b> ${order.unit_price} ${order.currency}</p>
                            <p class="pt-1 border-t border-indigo-200 mt-1"><b>Общая сумма:</b> <span class="font-bold text-lg">${order.total_amount} ${order.currency}</span></p>
                        </div>
                    `;
                }
            }

            document.getElementById('detModalBody').innerHTML = `
                <div class="space-y-2">
                    <div class="flex justify-between items-center">
                        <p><b>Статус:</b> ${statusBadge}</p>
                        <p class="text-xs text-gray-500">Дата: ${new Date(order.created_at).toLocaleDateString()}</p>
                    </div>
                    <p><b>Предприятие:</b> ${order.enterprise || '-'}</p>
                    <p><b>Направление:</b> ${order.requesting_dept_id} ➔ ${order.executing_dept_id}</p>
                    <p><b>Приоритет:</b> ${order.priority}</p>
                    <p><b>Спецификация:</b> ${order.specification || '-'}</p>
                    <div class="pt-1">
                        <label class="block text-xs font-semibold text-gray-600 mb-1">Техническое задание:</label>
                        ${downloadBtnHtml}
                    </div>
                    ${order.comment ? `<p class="mt-2 text-red-600"><b>Комментарий/История:</b> ${order.comment}</p>` : ''}
                    
                    <hr class="my-2">
                    <h4 class="font-bold text-gray-800">Запрос материала:</h4>
                    ${itemsDetails}
                    ${supplierInfoHtml}
                </div>
            `;

            let leftActionButtons = '';
            let rightActionButtons = `<button onclick="closeDetailModal()" class="px-4 py-2 text-sm font-medium text-gray-600 bg-gray-100 rounded-lg hover:bg-gray-200">Закрыть</button>`;
            let extraRejectHtml = '';
            
            if (order.status === 'Черновик') {
                // Кнопка редактирования только для черновиков!
                leftActionButtons = `<button onclick="openEditForm('${order.id}')" class="px-4 py-2 text-sm font-medium text-blue-700 bg-blue-50 border border-blue-200 rounded-lg hover:bg-blue-100 shadow">✏️ Редактировать</button>`;
                rightActionButtons += `<button onclick="changeStatus('${order.id}', 'На согласовании')" class="px-4 py-2 text-sm font-medium text-white bg-yellow-500 rounded-lg hover:bg-yellow-600 shadow">Отправить на согласование</button>`;
            } else if (order.status === 'На согласовании') {
                extraRejectHtml = `
                    <div class="w-full bg-red-50 p-3 rounded-lg border border-red-200 mb-2">
                        <label class="block text-xs font-semibold text-red-700 mb-1">Причина отказа (обязательно):</label>
                        <input type="text" id="rejectComment_${order.id}" placeholder="Опишите причину отклонения..." class="w-full border border-red-300 rounded-lg p-2 text-sm outline-none focus:ring-1 focus:ring-red-500 bg-white text-gray-800">
                    </div>
                `;
                rightActionButtons += `<button onclick="rejectOrder('${order.id}')" class="px-4 py-2 text-sm font-medium text-white bg-red-600 rounded-lg hover:bg-red-700 shadow">❌ Отказать</button>`;
                rightActionButtons += `<button onclick="changeStatus('${order.id}', 'Принят в работу')" class="px-4 py-2 text-sm font-medium text-white bg-purple-600 rounded-lg hover:bg-purple-700 shadow">✅ Утвердить (В работу)</button>`;
            } else if (order.status === 'Принят в работу') {
                rightActionButtons += `<button onclick="showSupplierForm('${order.id}', ${totalRequestedQty})" class="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 shadow">🛒 Сделать заказ поставщику</button>`;
            } else if (order.status === 'Заказан поставщику') {
                rightActionButtons += `<button onclick="changeStatus('${order.id}', 'На складе')" class="px-4 py-2 text-sm font-medium text-white bg-orange-500 rounded-lg hover:bg-orange-600 shadow">📦 Принять на склад</button>`;
            } else if (order.status === 'На складе') {
                rightActionButtons += `<button onclick="changeStatus('${order.id}', 'Выполнен')" class="px-4 py-2 text-sm font-medium text-white bg-green-600 rounded-lg hover:bg-green-700 shadow">✅ Выдать и завершить</button>`;
            }

            document.getElementById('detModalFooter').innerHTML = `
                ${extraRejectHtml}
                <div class="flex justify-between w-full">
                    <div>${leftActionButtons}</div>
                    <div class="flex gap-2">${rightActionButtons}</div>
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
    return {"status": "success", "id": new_order.id}

@app.put("/api/orders/{order_id}")
async def edit_order(order_id: str, order_data: OrderCreateSchema, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(OrderModel).filter_by(id=order_id))
    order = result.scalars().first()
    if not order:
        raise HTTPException(status_code=404, detail="Заказ не найден")
    
    if order.status != "Черновик":
        raise HTTPException(status_code=400, detail="Редактировать можно только черновики")

    # Обновляем основные поля
    order.enterprise = order_data.enterprise
    order.requesting_dept_id = order_data.requesting_dept_id
    order.executing_dept_id = order_data.executing_dept_id
    order.priority = order_data.priority
    order.planned_date = order_data.planned_date
    order.specification = order_data.specification
    order.tech_spec_file = order_data.tech_spec_file
    order.comment = order_data.comment
    
    # Удаляем старые позиции материала
    await db.execute(delete(OrderItemModel).where(OrderItemModel.order_id == order_id))
    
    # Добавляем обновленные позиции
    for item in order_data.items:
        new_item = OrderItemModel(**item.model_dump())
        new_item.order_id = order_id
        db.add(new_item)
        
    await db.commit()
    return {"status": "success", "id": order.id}

@app.patch("/api/orders/{order_id}/status")
async def update_order_status(order_id: str, payload: OrderStatusUpdateSchema, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(OrderModel).filter_by(id=order_id))
    order = result.scalars().first()
    if not order:
        raise HTTPException(status_code=404, detail="Заказ не найден")
    
    order.status = payload.status
    if payload.reject_comment:
        existing_comment = order.comment if order.comment else ""
        separator = " | " if existing_comment else ""
        order.comment = f"{existing_comment}{separator}[ОТКАЗ: {payload.reject_comment}]"

    if payload.supplier_name: order.supplier_name = payload.supplier_name
    if payload.contract_number: order.contract_number = payload.contract_number
    if payload.contract_date: order.contract_date = payload.contract_date
    if payload.currency: order.currency = payload.currency
    if payload.incoterms: order.incoterms = payload.incoterms
    if payload.ordered_quantity is not None: order.ordered_quantity = payload.ordered_quantity
    if payload.unit_price is not None: order.unit_price = payload.unit_price
    if payload.total_amount is not None: order.total_amount = payload.total_amount

    await db.commit()
    return {"status": "success", "new_status": order.status}

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
            "supplier_name": order.supplier_name,
            "contract_number": order.contract_number,
            "contract_date": order.contract_date,
            "currency": order.currency,
            "incoterms": order.incoterms,
            "ordered_quantity": order.ordered_quantity,
            "unit_price": order.unit_price,
            "total_amount": order.total_amount,
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
