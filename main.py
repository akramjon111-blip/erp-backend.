from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Float, Boolean, update, delete
from sqlalchemy.orm import declarative_base, relationship, selectinload
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.future import select
from datetime import datetime
from typing import List, Optional

# --- КОНФИГУРАЦИЯ ---
SECRET_KEY = "super_secret_key_change_me"
ALGORITHM = "HS256"
# ВАЖНО: Новое имя БД, чтобы сбросить старые кэши и ошибки таблиц!
DATABASE_URL = "sqlite+aiosqlite:///./erp_orders_v3.db"

# --- БАЗА ДАННЫХ ---
Base = declarative_base()

class OrderModel(Base):
    __tablename__ = "orders"
    id = Column(String, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    approved_at = Column(DateTime, nullable=True) 
    status = Column(String, default="Черновик")
    enterprise = Column(String, nullable=True)
    requesting_dept_id = Column(String)
    executing_dept_id = Column(String)
    priority = Column(String, default="Средний")
    planned_date = Column(String, nullable=True) 
    comment = Column(String, nullable=True)
    
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
    specification = Column(String, nullable=True) 
    tech_spec_file = Column(String, nullable=True)
    
    order = relationship("OrderModel", back_populates="items")
    contract_items = relationship("ContractItemModel", back_populates="order_item", cascade="all, delete-orphan")

# ТАБЛИЦА ДОГОВОРОВ (ГЛОБАЛЬНАЯ)
class ContractModel(Base):
    __tablename__ = "contracts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    supplier_name = Column(String)
    contract_number = Column(String)
    contract_date = Column(String)
    currency = Column(String)
    incoterms = Column(String)
    status = Column(String, default="Заказан поставщику")
    total_amount = Column(Float, default=0)
    
    items = relationship("ContractItemModel", back_populates="contract", cascade="all, delete-orphan")

class ContractItemModel(Base):
    __tablename__ = "contract_items"
    id = Column(Integer, primary_key=True, autoincrement=True)
    contract_id = Column(Integer, ForeignKey("contracts.id"))
    order_item_id = Column(Integer, ForeignKey("order_items.id"))
    
    ordered_quantity = Column(Float)
    unit_price = Column(Float)
    
    contract = relationship("ContractModel", back_populates="items")
    order_item = relationship("OrderItemModel", back_populates="contract_items")

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

# --- PYDANTIC СХЕМЫ ---
class OrderItemBase(BaseModel):
    material_code: str
    name: str
    unit: str
    requested_quantity: float
    allow_analog: bool = True
    specification: Optional[str] = "-" 
    tech_spec_file: Optional[str] = "-" 

class OrderCreateSchema(BaseModel):
    id: Optional[str] = ""  
    enterprise: Optional[str] = None  
    requesting_dept_id: str
    executing_dept_id: str
    priority: Optional[str] = "Средний"
    planned_date: Optional[str] = "Не указана"
    comment: Optional[str] = None
    items: List[OrderItemBase]

class ContractItemSchema(BaseModel):
    order_item_id: int
    ordered_quantity: float
    unit_price: float

class ContractCreateSchema(BaseModel):
    supplier_name: str
    contract_number: str
    contract_date: str
    currency: str
    incoterms: str
    items: List[ContractItemSchema]

class StatusUpdateSchema(BaseModel):
    status: str
    reject_comment: Optional[str] = None

class ContractStatusUpdateSchema(BaseModel):
    status: str

# --- ПРИЛОЖЕНИЕ ---
app = FastAPI(title="ERP API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    <title>ERP Закупки</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-100 font-sans antialiased h-screen flex flex-col relative">

    <header class="bg-blue-600 text-white p-4 shadow-md flex justify-between items-center z-10">
        <h1 class="text-xl font-bold">ERP Закупки</h1>
        <div id="headerActions">
            <button id="fabAddOrder" class="bg-blue-700 hover:bg-blue-800 text-white px-3 py-1.5 rounded-lg font-medium text-sm flex items-center gap-1 transition shadow-sm">
                + Новый заказ
            </button>
        </div>
    </header>

    <!-- ВКЛАДКИ -->
    <div class="bg-white border-b border-gray-200 flex px-4">
        <button id="tabOrders" class="px-4 py-3 font-bold border-b-2 border-blue-600 text-blue-600 transition" onclick="switchTab('orders')">Мои заказы</button>
        <button id="tabContracts" class="px-4 py-3 font-bold border-b-2 border-transparent text-gray-500 hover:text-gray-700 transition" onclick="switchTab('contracts')">Договоры поставки</button>
    </div>

    <main class="flex-1 overflow-y-auto p-4" id="mainContent">
        <div class="flex items-center justify-center h-full">
            <p class="text-gray-500 text-center">Загрузка данных...</p>
        </div>
    </main>

    <!-- МОДАЛКИ ЗАКАЗОВ -->
    <div id="orderModal" class="fixed inset-0 bg-black bg-opacity-50 hidden flex items-center justify-center z-50 p-4">
        <div class="bg-white p-6 rounded-xl w-full max-w-lg shadow-2xl max-h-[90vh] overflow-y-auto">
            <h2 id="orderModalTitle" class="text-lg font-bold mb-4 text-gray-800">Создание нового заказа</h2>
            <form id="orderForm" class="space-y-4">
                <div class="grid grid-cols-2 gap-3">
                    <div>
                        <label class="block text-xs font-semibold text-gray-600 mb-1">Предприятие</label>
                        <select id="enterprise" class="w-full border border-gray-300 rounded-lg p-2 text-sm bg-white">
                            <option value="" selected>Выберите предприятие...</option>
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
                        <input type="text" id="reqDept" required class="w-full border border-gray-300 rounded-lg p-2 text-sm" placeholder="Например: IT">
                    </div>
                    <div>
                        <label class="block text-xs font-semibold text-gray-600 mb-1">Исполняющий отдел</label>
                        <input type="text" id="execDept" required class="w-full border border-gray-300 rounded-lg p-2 text-sm" placeholder="Например: Закупок">
                    </div>
                </div>
                <div class="grid grid-cols-2 gap-3">
                    <div>
                        <label class="block text-xs font-semibold text-gray-600 mb-1">Необходимая дата</label>
                        <input type="date" id="plannedDate" class="w-full border border-gray-300 rounded-lg p-2 text-sm">
                    </div>
                    <div>
                        <label class="block text-xs font-semibold text-gray-600 mb-1">Общий комментарий</label>
                        <textarea id="orderComment" rows="1" class="w-full border border-gray-300 rounded-lg p-2 text-sm resize-y" placeholder="Примечания..."></textarea>
                    </div>
                </div>
                <hr class="my-3 border-gray-200">
                <div class="flex justify-between items-center mb-2">
                    <h3 class="font-bold text-sm text-gray-700">Позиции (Товары / Услуги)</h3>
                    <button type="button" onclick="addItemRow()" class="bg-blue-100 text-blue-700 hover:bg-blue-200 px-3 py-1 rounded-lg text-xs font-bold transition shadow-sm">+ Добавить позицию</button>
                </div>
                <div id="itemsContainer" class="space-y-3"></div>
                <div class="flex justify-end space-x-2 mt-5 pt-3 border-t border-gray-200">
                    <button type="button" onclick="closeModal('orderModal')" class="px-4 py-2 text-sm font-medium text-gray-600 bg-gray-100 rounded-lg hover:bg-gray-200">Отмена</button>
                    <button type="submit" id="submitOrderBtn" class="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700">Создать заказ</button>
                </div>
            </form>
        </div>
    </div>

    <div id="orderDetailModal" class="fixed inset-0 bg-black bg-opacity-50 hidden flex items-center justify-center z-50 p-4">
        <div class="bg-white p-6 rounded-xl w-full max-w-2xl shadow-2xl max-h-[95vh] overflow-y-auto">
            <div class="flex justify-between items-center mb-4 border-b pb-2">
                <h2 id="ordDetTitle" class="text-lg font-bold text-gray-800">Детали заказа</h2>
                <button onclick="closeModal('orderDetailModal')" class="text-gray-400 hover:text-gray-600 font-bold text-lg">&times;</button>
            </div>
            <div id="ordDetBody" class="space-y-4 text-sm text-gray-700"></div>
            <div id="ordDetFooter" class="mt-6 pt-3 border-t flex flex-col gap-3"></div>
        </div>
    </div>

    <!-- МОДАЛКИ ДОГОВОРОВ -->
    <div id="contractModal" class="fixed inset-0 bg-black bg-opacity-50 hidden flex items-center justify-center z-50 p-4">
        <div class="bg-white p-6 rounded-xl w-full max-w-3xl shadow-2xl max-h-[95vh] overflow-y-auto">
            <h2 class="text-lg font-bold mb-4 text-indigo-800">Создание нового договора поставки</h2>
            <form id="contractForm" class="space-y-4">
                <div class="bg-indigo-50 p-3 rounded-lg border border-indigo-100 grid grid-cols-3 gap-3">
                    <div>
                        <label class="block text-xs font-semibold text-gray-700 mb-1">Поставщик</label>
                        <input type="text" id="cSupName" required class="w-full border border-gray-300 rounded p-1.5 text-sm" placeholder="ООО...">
                    </div>
                    <div>
                        <label class="block text-xs font-semibold text-gray-700 mb-1">Номер договора</label>
                        <input type="text" id="cNum" required class="w-full border border-gray-300 rounded p-1.5 text-sm" placeholder="№">
                    </div>
                    <div>
                        <label class="block text-xs font-semibold text-gray-700 mb-1">Дата договора</label>
                        <input type="date" id="cDate" required class="w-full border border-gray-300 rounded p-1.5 text-sm">
                    </div>
                    <div>
                        <label class="block text-xs font-semibold text-gray-700 mb-1">Валюта</label>
                        <select id="cCur" class="w-full border border-gray-300 rounded p-1.5 text-sm bg-white">
                            <option>AZN</option><option>USD</option><option>EUR</option><option>RUB</option>
                        </select>
                    </div>
                    <div>
                        <label class="block text-xs font-semibold text-gray-700 mb-1">Инкотермс</label>
                        <select id="cInco" class="w-full border border-gray-300 rounded p-1.5 text-sm bg-white">
                            <option>EXW</option><option>FCA</option><option>CPT</option><option>CIP</option><option>DAP</option><option>DDP</option>
                        </select>
                    </div>
                    <div>
                        <label class="block text-xs font-semibold text-gray-700 mb-1">Общая сумма договора</label>
                        <input type="text" id="cTotal" readonly class="w-full bg-indigo-100 border border-indigo-200 rounded p-1.5 text-sm font-bold text-indigo-900" value="0.00">
                    </div>
                </div>

                <hr class="border-gray-200">
                <div class="flex gap-2 items-end">
                    <div class="flex-1">
                        <label class="block text-xs font-semibold text-indigo-700 mb-1">Выберите товары из заявок для этого договора:</label>
                        <select id="cAvailItems" class="w-full border border-indigo-300 rounded p-2 text-sm bg-white font-medium shadow-sm"></select>
                    </div>
                    <button type="button" onclick="addContractRow()" class="bg-indigo-600 text-white px-3 py-2 rounded text-sm font-bold hover:bg-indigo-700 whitespace-nowrap shadow-sm">+ Добавить товар</button>
                </div>

                <div id="cRowsContainer" class="space-y-2 mt-3"></div>

                <div class="flex justify-end space-x-2 mt-5 pt-3 border-t border-gray-200">
                    <button type="button" onclick="closeModal('contractModal')" class="px-4 py-2 text-sm font-medium text-gray-600 bg-gray-100 rounded-lg hover:bg-gray-200">Отмена</button>
                    <button type="submit" class="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700">Сохранить договор</button>
                </div>
            </form>
        </div>
    </div>

    <div id="contractDetailModal" class="fixed inset-0 bg-black bg-opacity-50 hidden flex items-center justify-center z-50 p-4">
        <div class="bg-white p-6 rounded-xl w-full max-w-2xl shadow-2xl max-h-[95vh] overflow-y-auto">
            <div class="flex justify-between items-center mb-4 border-b pb-2">
                <h2 id="conDetTitle" class="text-lg font-bold text-indigo-800">Детали договора</h2>
                <button onclick="closeModal('contractDetailModal')" class="text-gray-400 hover:text-gray-600 font-bold text-lg">&times;</button>
            </div>
            <div id="conDetBody" class="space-y-4 text-sm text-gray-700"></div>
            <div id="conDetFooter" class="mt-6 pt-3 border-t flex justify-end gap-2"></div>
        </div>
    </div>

    <script>
        let currentTab = 'orders';
        let ordersCache = [];
        let contractsCache = [];
        let editingOrderId = null;

        // --- УПРАВЛЕНИЕ ВКЛАДКАМИ ---
        function switchTab(tab) {
            currentTab = tab;
            document.getElementById('tabOrders').className = `px-4 py-3 font-bold transition border-b-2 ${tab === 'orders' ? 'border-blue-600 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700'}`;
            document.getElementById('tabContracts').className = `px-4 py-3 font-bold transition border-b-2 ${tab === 'contracts' ? 'border-indigo-600 text-indigo-600' : 'border-transparent text-gray-500 hover:text-gray-700'}`;
            
            const btnContainer = document.getElementById('headerActions');
            if(tab === 'orders') {
                btnContainer.innerHTML = `<button onclick="openOrderModal()" class="bg-blue-700 hover:bg-blue-800 text-white px-3 py-1.5 rounded-lg font-medium text-sm flex items-center gap-1 shadow-sm">+ Новый заказ</button>`;
            } else {
                btnContainer.innerHTML = `<button onclick="openContractModal()" class="bg-indigo-600 hover:bg-indigo-700 text-white px-3 py-1.5 rounded-lg font-medium text-sm flex items-center gap-1 shadow-sm">+ Создать договор</button>`;
            }
            renderApp();
        }

        document.getElementById('fabAddOrder').addEventListener('click', openOrderModal);
        function closeModal(id) { document.getElementById(id).classList.add('hidden'); }

        async function fetchData() {
            try {
                const [resOrd, resCon] = await Promise.all([ fetch('/api/orders'), fetch('/api/contracts') ]);
                ordersCache = await resOrd.json();
                contractsCache = await resCon.json();
                renderApp();
            } catch (err) {
                document.getElementById('mainContent').innerHTML = '<p class="text-red-500 text-center mt-10">Ошибка загрузки данных. Пожалуйста, обновите страницу (Ctrl+F5).</p>';
            }
        }

        function renderApp() {
            const main = document.getElementById('mainContent');
            if (currentTab === 'orders') renderOrders(main);
            else renderContracts(main);
        }

        // ================= ЗАКАЗЫ =================
        function openOrderModal() {
            editingOrderId = null;
            document.getElementById('orderModalTitle').innerText = 'Создание нового заказа';
            document.getElementById('orderForm').reset();
            document.getElementById('itemsContainer').innerHTML = '';
            addItemRow();
            document.getElementById('orderModal').classList.remove('hidden');
        }

        function addItemRow(data = null) {
            const row = document.createElement('div');
            row.className = 'item-row bg-gray-50 p-3 rounded-lg border border-gray-200 relative shadow-sm';
            let fileBox = data && data.tech_spec_file && data.tech_spec_file !== '-' && data.tech_spec_file !== 'Не прикреплен' 
                ? `<div class="mb-1 text-xs text-blue-700 bg-blue-50 px-2 py-1 rounded flex justify-between">
                    <span class="c-file" data-file="${data.tech_spec_file}">${data.tech_spec_file}</span>
                    <button type="button" onclick="this.parentElement.remove()" class="text-red-500">✕</button>
                   </div>` : '';

            row.innerHTML = `
                <button type="button" onclick="this.closest('.item-row').remove()" class="absolute top-2 right-2 text-red-500 text-xs font-bold px-2 py-0.5 border border-red-200 bg-white rounded shadow-sm">✕ Удалить</button>
                <div class="grid grid-cols-3 gap-2 mb-2 pr-20">
                    <div class="col-span-1"><label class="text-xs">Код</label><input type="text" class="i-code w-full border rounded p-1.5 text-xs" required value="${data?.material_code || ''}"></div>
                    <div class="col-span-2"><label class="text-xs">Наименование</label><input type="text" class="i-name w-full border rounded p-1.5 text-xs" required value="${data?.name || ''}"></div>
                </div>
                <div class="grid grid-cols-3 gap-2 mb-2">
                    <div><label class="text-xs">Кол-во</label><input type="number" class="i-qty w-full border rounded p-1.5 text-xs" required min="0.01" value="${data?.requested_quantity || 1}"></div>
                    <div><label class="text-xs">Ед. изм.</label><input type="text" class="i-unit w-full border rounded p-1.5 text-xs" required value="${data?.unit || 'шт'}"></div>
                    <div><label class="text-xs">Аналог</label><select class="i-analog w-full border rounded p-1.5 text-xs"><option value="true" ${data?.allow_analog===true?'selected':''}>Да</option><option value="false" ${data?.allow_analog===false?'selected':''}>Нет</option></select></div>
                </div>
                <div class="mb-2"><label class="text-xs">Спецификация</label><textarea class="i-spec w-full border rounded p-1.5 text-xs resize-y" rows="1">${data?.specification || ''}</textarea></div>
                <div class="mt-2 pt-2 border-t"><label class="text-xs">ТЗ файла</label>${fileBox}<input type="file" class="i-file w-full border rounded p-1 text-xs"></div>
            `;
            document.getElementById('itemsContainer').appendChild(row);
        }

        document.getElementById('orderForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const itemsList = [];
            document.querySelectorAll('.item-row').forEach(row => {
                const fInput = row.querySelector('.i-file');
                const cFile = row.querySelector('.c-file');
                let fname = 'Не прикреплен';
                if(fInput.files.length > 0) fname = fInput.files[0].name;
                else if (cFile) fname = cFile.getAttribute('data-file');

                itemsList.push({
                    material_code: row.querySelector('.i-code').value.trim() || '-',
                    name: row.querySelector('.i-name').value.trim(),
                    unit: row.querySelector('.i-unit').value.trim(),
                    requested_quantity: parseFloat(row.querySelector('.i-qty').value) || 1,
                    allow_analog: row.querySelector('.i-analog').value === 'true',
                    specification: row.querySelector('.i-spec').value.trim() || '-',
                    tech_spec_file: fname
                });
            });

            if(itemsList.length === 0) return alert('Добавьте позиции!');

            const payload = {
                id: editingOrderId || "",
                enterprise: document.getElementById('enterprise').value,
                requesting_dept_id: document.getElementById('reqDept').value,
                executing_dept_id: document.getElementById('execDept').value,
                priority: document.getElementById('priority').value,
                planned_date: document.getElementById('plannedDate').value,
                comment: document.getElementById('orderComment').value,
                items: itemsList
            };

            const url = editingOrderId ? `/api/orders/${editingOrderId}` : '/api/orders';
            const method = editingOrderId ? 'PUT' : 'POST';

            try {
                const res = await fetch(url, { method, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload) });
                if(res.ok) { closeModal('orderModal'); fetchData(); } else alert('Ошибка сервера');
            } catch(e) { alert('Ошибка сети'); }
        });

        function renderOrders(container) {
            if(ordersCache.length === 0) {
                container.innerHTML = '<p class="text-gray-500 text-center mt-10">Заказов пока нет</p>';
                return;
            }
            let html = '<div class="space-y-4 max-w-3xl mx-auto pb-10">';
            ordersCache.forEach(o => {
                let pColor = o.priority==='Высокий'?'bg-red-100 text-red-700':'bg-gray-100 text-gray-700';
                
                let sColor = 'bg-gray-200';
                if(o.status==='Черновик') sColor='bg-gray-200 border border-gray-300';
                if(o.status==='На согласовании') sColor='bg-yellow-100 text-yellow-700';
                if(o.status==='Принят в работу') sColor='bg-purple-100 text-purple-700';
                if(o.status==='В процессе закупки') sColor='bg-indigo-100 text-indigo-700';
                if(o.status==='Заказан поставщику') sColor='bg-cyan-100 text-cyan-700';
                if(o.status==='На складе') sColor='bg-orange-100 text-orange-700';
                if(o.status==='Выполнен') sColor='bg-green-100 text-green-700';

                let reqTotal=0, ordTotal=0;
                o.items.forEach(i => {
                    reqTotal += i.requested_quantity;
                    if(i.contract_items) i.contract_items.forEach(ci => ordTotal += ci.ordered_quantity);
                });

                let progress = o.status!=='Черновик'&&o.status!=='На согласовании' 
                    ? `<span class="ml-2 text-xs font-bold px-1.5 py-0.5 rounded ${ordTotal>=reqTotal?'bg-green-100 text-green-700':'bg-blue-100 text-blue-700'}">По договорам: ${ordTotal}/${reqTotal}</span>` : '';

                html += `
                    <div onclick="openOrderDetail('${o.id}')" class="bg-white p-4 rounded-xl shadow-sm border border-gray-200 hover:border-blue-400 cursor-pointer transition">
                        <div class="flex justify-between mb-2">
                            <div>
                                <h3 class="font-bold text-gray-900 inline-block mr-2">Заказ #${o.id}</h3>
                                <span class="text-xs font-semibold px-2 py-0.5 rounded ${pColor}">${o.priority}</span>
                            </div>
                            <span class="text-xs font-bold px-2 py-1 rounded ${sColor}">${o.status}</span>
                        </div>
                        <p class="text-xs text-gray-500 mb-2">🏭 ${o.enterprise||'Не указ.'} | ${o.requesting_dept_id} ➔ ${o.executing_dept_id}</p>
                        <div class="text-xs flex gap-3 flex-wrap">
                            <span>📅 ${o.planned_date||'-'}</span>
                            ${progress}
                        </div>
                    </div>
                `;
            });
            container.innerHTML = html + '</div>';
        }

        function openOrderDetail(oId) {
            const o = ordersCache.find(x => x.id === oId);
            if(!o) return;
            document.getElementById('ordDetTitle').innerText = `Заказ #${o.id} (${o.status})`;
            
            let html = `
                <div class="grid grid-cols-2 gap-2 text-xs bg-gray-50 p-2 rounded mb-3">
                    <div><b>Создан:</b> ${new Date(o.created_at).toLocaleDateString()}</div>
                    <div><b>Утвержден:</b> ${o.approved_at ? new Date(o.approved_at).toLocaleDateString() : '-'}</div>
                </div>
                <p><b>Направление:</b> ${o.requesting_dept_id} ➔ ${o.executing_dept_id}</p>
                ${o.comment ? `<div class="text-xs bg-red-50 text-red-700 p-2 rounded mt-2 border-l-2 border-red-400 whitespace-pre-wrap">${o.comment}</div>` : ''}
                
                <h4 class="font-bold mt-4 mb-2">Позиции:</h4>
                <div class="space-y-2">
            `;
            
            o.items.forEach(i => {
                let ordered = 0;
                let cBadges = '';
                if(i.contract_items && i.contract_items.length > 0) {
                    i.contract_items.forEach(ci => {
                        ordered += ci.ordered_quantity;
                        let statusClr = ci.status === 'Выполнен' ? 'text-green-700 bg-green-100' : (ci.status === 'На складе' ? 'text-orange-700 bg-orange-100' : 'text-indigo-700 bg-indigo-100');
                        cBadges += `<span class="${statusClr} text-xs px-1.5 py-0.5 rounded mr-1 border border-gray-200" title="Поставщик: ${ci.supplier}">В договоре: ${ci.ordered_quantity} шт.</span>`;
                    });
                }
                
                let rem = i.requested_quantity - ordered;
                let stateBadge = rem <= 0 ? `<span class="text-green-600 text-xs font-bold">✓ Закуплено полностью</span>` : `<span class="text-yellow-600 text-xs font-bold bg-yellow-50 px-1 rounded">Осталось: ${rem}</span>`;

                html += `
                    <div class="border p-2 rounded bg-gray-50 text-xs relative">
                        <div class="flex justify-between font-bold text-sm mb-1">
                            <span>${i.name} <span class="text-gray-400 font-normal">(${i.material_code})</span></span>
                            <span>${i.requested_quantity} ${i.unit}</span>
                        </div>
                        <div class="flex justify-between items-center mt-2 border-t pt-2">
                            <div class="flex flex-wrap gap-1">${cBadges || '<span class="text-gray-400 italic">Ждет оформления договора</span>'}</div>
                            ${stateBadge}
                        </div>
                    </div>
                `;
            });
            html += '</div>';

            // Если есть договоры, покажем их сводку
            if(o.contracts && o.contracts.length > 0) {
                html += '<h4 class="font-bold mt-4 mb-2">Связанные договоры:</h4><div class="space-y-2">';
                o.contracts.forEach(c => {
                    let sColor = c.status==='Выполнен'?'text-green-700':'text-indigo-700';
                    html += `<div class="p-2 border rounded bg-indigo-50 text-xs"><b>Договор №${c.contract_number}</b> (${c.supplier_name}) — <span class="font-bold ${sColor}">${c.status}</span></div>`;
                });
                html += '</div>';
            }

            document.getElementById('ordDetBody').innerHTML = html;

            let footer = '';
            if(o.status === 'Черновик') {
                footer = `
                    <button onclick="editOrder('${o.id}')" class="px-4 py-2 bg-blue-100 text-blue-700 rounded font-bold">✏️ Изменить</button>
                    <button onclick="updateOrderStatus('${o.id}', 'На согласовании')" class="px-4 py-2 bg-yellow-500 text-white rounded font-bold">На согласование</button>
                `;
            } else if (o.status === 'На согласовании') {
                footer = `
                    <button onclick="rejectOrder('${o.id}')" class="px-4 py-2 bg-red-600 text-white rounded font-bold">❌ Отказать</button>
                    <button onclick="updateOrderStatus('${o.id}', 'Принят в работу')" class="px-4 py-2 bg-purple-600 text-white rounded font-bold">Утвердить (В работу)</button>
                `;
            } else {
                footer = `<span class="text-sm text-gray-500 italic bg-gray-100 p-2 rounded w-full text-center">Закупка и движение по складам теперь оформляется во вкладке <b>"Договоры поставки"</b>.</span>`;
            }
            document.getElementById('ordDetFooter').innerHTML = footer;
            document.getElementById('orderDetailModal').classList.remove('hidden');
        }

        function editOrder(oId) {
            closeModal('orderDetailModal');
            const o = ordersCache.find(x => x.id === oId);
            editingOrderId = o.id;
            document.getElementById('orderModalTitle').innerText = `Редактирование #${o.id}`;
            document.getElementById('enterprise').value = o.enterprise||'';
            document.getElementById('priority').value = o.priority;
            document.getElementById('reqDept').value = o.requesting_dept_id;
            document.getElementById('execDept').value = o.executing_dept_id;
            document.getElementById('plannedDate').value = o.planned_date;
            document.getElementById('orderComment').value = o.comment||'';
            document.getElementById('itemsContainer').innerHTML = '';
            o.items.forEach(i => addItemRow(i));
            document.getElementById('orderModal').classList.remove('hidden');
        }

        async function updateOrderStatus(id, st, comment=null) {
            try {
                await fetch(`/api/orders/${id}/status`, { method: 'PATCH', headers: {'Content-Type':'application/json'}, body: JSON.stringify({status: st, reject_comment: comment}) });
                closeModal('orderDetailModal');
                fetchData();
            } catch(e) {}
        }

        function rejectOrder(id) {
            let reason = prompt('Причина отказа:');
            if(reason) updateOrderStatus(id, 'Черновик', reason);
        }

        // ================= ДОГОВОРЫ =================
        function openContractModal() {
            document.getElementById('contractForm').reset();
            document.getElementById('cRowsContainer').innerHTML = '';
            document.getElementById('cTotal').value = '0.00';
            populateContractItemsDropdown();
            document.getElementById('contractModal').classList.remove('hidden');
        }

        function populateContractItemsDropdown() {
            let opts = '<option value="" disabled selected>Выберите товар из утвержденных заявок...</option>';
            ordersCache.forEach(o => {
                if(o.status === 'Черновик' || o.status === 'На согласовании') return;
                o.items.forEach(i => {
                    let ord = 0;
                    if(i.contract_items) i.contract_items.forEach(c => ord += c.ordered_quantity);
                    let rem = i.requested_quantity - ord;
                    if(rem > 0) {
                        opts += `<option value="${i.id}" data-max="${rem}" data-name="${i.name}" data-order="${o.id}">Заказ ${o.id} | ${i.name} (Нужно: ${rem})</option>`;
                    }
                });
            });
            document.getElementById('cAvailItems').innerHTML = opts;
        }

        function addContractRow() {
            const sel = document.getElementById('cAvailItems');
            if(!sel.value) return alert('Выберите позицию из списка!');
            const opt = sel.options[sel.selectedIndex];
            const iid = opt.value;
            
            if(document.querySelector(`.c-row[data-iid="${iid}"]`)) return alert('Эта позиция уже в списке ниже!');

            const max = opt.getAttribute('data-max');
            const name = opt.getAttribute('data-name');
            const ord = opt.getAttribute('data-order');

            const div = document.createElement('div');
            div.className = `c-row bg-white border border-indigo-200 p-2 rounded flex gap-2 items-center text-sm`;
            div.setAttribute('data-iid', iid);
            div.innerHTML = `
                <div class="flex-1 font-bold text-gray-700 bg-gray-100 px-2 py-1 rounded">${ord} <span class="font-normal">| ${name}</span></div>
                <div>
                    <span class="text-xs text-gray-500 block mb-0.5">Кол-во (макс ${max})</span>
                    <input type="number" class="cr-qty w-20 border border-gray-300 rounded p-1" value="${max}" max="${max}" oninput="calcContractTotal()" required>
                </div>
                <div>
                    <span class="text-xs text-gray-500 block mb-0.5">Цена/шт</span>
                    <input type="number" step="0.01" class="cr-price w-24 border border-gray-300 rounded p-1" placeholder="0.00" oninput="calcContractTotal()" required>
                </div>
                <div class="font-bold text-indigo-700 w-24 text-right cr-sum mt-4">0.00</div>
                <button type="button" onclick="this.parentElement.remove(); calcContractTotal()" class="text-red-500 font-bold ml-2 mt-4 hover:bg-red-50 px-2 rounded">✕</button>
            `;
            document.getElementById('cRowsContainer').appendChild(div);
            sel.value = "";
        }

        function calcContractTotal() {
            let total = 0;
            document.querySelectorAll('.c-row').forEach(row => {
                const qtyInput = row.querySelector('.cr-qty');
                let max = parseFloat(qtyInput.getAttribute('max'));
                let q = parseFloat(qtyInput.value)||0;
                if(q > max) { q = max; qtyInput.value = max; alert('Количество превышает остаток по заявке!'); }
                let p = parseFloat(row.querySelector('.cr-price').value)||0;
                let sum = q * p;
                row.querySelector('.cr-sum').innerText = sum.toFixed(2);
                total += sum;
            });
            document.getElementById('cTotal').value = total.toFixed(2);
        }

        document.getElementById('contractForm').addEventListener('submit', async(e) => {
            e.preventDefault();
            const items = [];
            document.querySelectorAll('.c-row').forEach(row => {
                items.push({
                    order_item_id: parseInt(row.getAttribute('data-iid')),
                    ordered_quantity: parseFloat(row.querySelector('.cr-qty').value),
                    unit_price: parseFloat(row.querySelector('.cr-price').value)
                });
            });
            if(items.length === 0) return alert('Вы не добавили ни одного товара в договор!');

            const payload = {
                supplier_name: document.getElementById('cSupName').value,
                contract_number: document.getElementById('cNum').value,
                contract_date: document.getElementById('cDate').value,
                currency: document.getElementById('cCur').value,
                incoterms: document.getElementById('cInco').value,
                items: items
            };

            try {
                const res = await fetch('/api/contracts', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload) });
                if(res.ok) { closeModal('contractModal'); fetchData(); } else alert('Ошибка сохранения договора');
            } catch(e) { alert('Ошибка сети'); }
        });

        function renderContracts(container) {
            if(contractsCache.length === 0) {
                container.innerHTML = '<p class="text-gray-500 text-center mt-10">Оформленных договоров пока нет</p>';
                return;
            }
            let html = '<div class="space-y-4 max-w-3xl mx-auto pb-10">';
            contractsCache.forEach(c => {
                let sColor = c.status==='Заказан поставщику' ? 'bg-indigo-100 text-indigo-700' : (c.status==='На складе' ? 'bg-orange-100 text-orange-700' : 'bg-green-100 text-green-700');
                html += `
                    <div onclick="openContractDetail('${c.id}')" class="bg-white p-4 rounded-xl shadow-sm border border-gray-200 hover:border-indigo-400 cursor-pointer transition">
                        <div class="flex justify-between mb-2">
                            <h3 class="font-bold text-indigo-900">Договор №${c.contract_number} <span class="font-normal text-gray-500">от ${c.contract_date}</span></h3>
                            <span class="text-xs font-bold px-2 py-1 rounded ${sColor}">${c.status}</span>
                        </div>
                        <p class="text-sm font-medium mb-2">🏢 Поставщик: ${c.supplier_name}</p>
                        <div class="flex justify-between text-xs text-gray-600 bg-gray-50 p-2 rounded">
                            <span>Условия: ${c.incoterms}, ${c.currency} | Позиций: ${c.items.length}</span>
                            <span class="font-bold text-sm text-gray-900">Сумма: ${c.total_amount} ${c.currency}</span>
                        </div>
                    </div>
                `;
            });
            container.innerHTML = html + '</div>';
        }

        function openContractDetail(cId) {
            const c = contractsCache.find(x => x.id === parseInt(cId));
            if(!c) return;
            document.getElementById('conDetTitle').innerText = `Договор №${c.contract_number}`;
            
            let html = `
                <div class="grid grid-cols-2 gap-2 text-sm bg-indigo-50 p-3 rounded mb-3 border border-indigo-100">
                    <div><b>Поставщик:</b> ${c.supplier_name}</div>
                    <div><b>Дата:</b> ${c.contract_date}</div>
                    <div><b>Условия:</b> ${c.incoterms}, ${c.currency}</div>
                    <div><b>Сумма:</b> <span class="font-bold text-indigo-700 text-base">${c.total_amount} ${c.currency}</span></div>
                </div>
                <h4 class="font-bold mt-4 mb-2">Включенные позиции:</h4>
                <div class="space-y-2">
            `;
            
            c.items.forEach(ci => {
                html += `
                    <div class="border p-2 rounded flex justify-between items-center text-xs bg-gray-50">
                        <div>
                            <span class="font-bold text-indigo-800 bg-white border px-1.5 py-0.5 rounded mr-2">Заказ #${ci.order_item.order_id}</span>
                            <span class="font-medium text-gray-800">${ci.order_item.name}</span>
                        </div>
                        <div class="text-right">
                            <div class="font-bold text-sm">${ci.ordered_quantity} шт.</div>
                            <div class="text-gray-500">${ci.unit_price} ${c.currency}/шт</div>
                        </div>
                    </div>
                `;
            });
            html += '</div>';
            document.getElementById('conDetBody').innerHTML = html;

            let footer = '';
            if(c.status === 'Заказан поставщику') {
                footer = `<button onclick="updateContractStatus(${c.id}, 'На складе')" class="px-4 py-2 bg-orange-500 text-white rounded font-bold shadow-sm">📦 Принять товары на склад</button>`;
            } else if (c.status === 'На складе') {
                footer = `<button onclick="updateContractStatus(${c.id}, 'Выполнен')" class="px-4 py-2 bg-green-600 text-white rounded font-bold shadow-sm">✅ Выдать (Завершить договор)</button>`;
            } else {
                 footer = `<span class="text-green-600 font-bold w-full text-center">Все обязательства по договору выполнены.</span>`;
            }
            document.getElementById('conDetFooter').innerHTML = footer;
            document.getElementById('contractDetailModal').classList.remove('hidden');
        }

        async function updateContractStatus(cId, status) {
            try {
                await fetch(`/api/contracts/${cId}/status`, { method: 'PATCH', headers: {'Content-Type':'application/json'}, body: JSON.stringify({status: status}) });
                closeModal('contractDetailModal');
                fetchData();
            } catch(e) {}
        }

        // Запуск при загрузке страницы
        switchTab('orders');
    </script>
</body>
</html>
"""

@app.get("/app", response_class=HTMLResponse)
async def web_app():
    return HTMLResponse(content=HTML_CONTENT)

# --- УТИЛИТА: ПЕРЕСЧЕТ СТАТУСОВ ЗАКАЗОВ ---
async def recalculate_orders(db: AsyncSession, order_ids: set):
    for oid in order_ids:
        res = await db.execute(select(OrderModel).options(
            selectinload(OrderModel.items).selectinload(OrderItemModel.contract_items).selectinload(ContractItemModel.contract)
        ).filter_by(id=oid))
        order = res.scalars().first()
        if not order: continue

        total_req = sum(i.requested_quantity for i in order.items)
        total_ord = 0
        all_contracts_done = True
        all_contracts_stocked_or_done = True
        has_contracts = False

        for item in order.items:
            for ci in item.contract_items:
                total_ord += ci.ordered_quantity
                has_contracts = True
                c_status = ci.contract.status
                if c_status != "Выполнен": all_contracts_done = False
                if c_status not in ["На складе", "Выполнен"]: all_contracts_stocked_or_done = False

        if not has_contracts:
            order.status = "Принят в работу"
        elif total_ord < total_req:
            order.status = "В процессе закупки"
        else: # Все объемы покрыты
            if all_contracts_done: order.status = "Выполнен"
            elif all_contracts_stocked_or_done: order.status = "На складе"
            else: order.status = "Заказан поставщику"

        db.add(order)
    await db.commit()

# --- API ЗАКАЗОВ ---
@app.post("/api/orders", response_model=dict)
async def create_order(order_data: OrderCreateSchema, db: AsyncSession = Depends(get_db)):
    order_id = order_data.id
    if not order_id:
        dept = order_data.requesting_dept_id.strip() if order_data.requesting_dept_id else "DEP"
        abbr = "".join([w[0] for w in dept.split()])[:3].upper() if len(dept.split())>1 else dept[:3].upper()
        now = datetime.utcnow()
        base_id = f"{abbr}-{now.strftime('%m.%Y')}."
        res = await db.execute(select(OrderModel))
        count = len(res.scalars().all())
        order_id = base_id + str(count + 1).zfill(3)
        while (await db.execute(select(OrderModel).filter_by(id=order_id))).scalars().first():
            count += 1; order_id = base_id + str(count + 1).zfill(3)

    new_order = OrderModel(
        id=order_id, enterprise=order_data.enterprise, requesting_dept_id=order_data.requesting_dept_id,
        executing_dept_id=order_data.executing_dept_id, priority=order_data.priority, 
        planned_date=order_data.planned_date, comment=order_data.comment, status="Черновик"
    )
    for i in order_data.items:
        new_order.items.append(OrderItemModel(**i.model_dump()))
    
    db.add(new_order)
    await db.commit()
    return {"status": "success"}

@app.put("/api/orders/{order_id}")
async def edit_order(order_id: str, order_data: OrderCreateSchema, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(OrderModel).filter_by(id=order_id))
    order = res.scalars().first()
    if not order or order.status != "Черновик": raise HTTPException(400)
    
    order.enterprise = order_data.enterprise
    order.requesting_dept_id = order_data.requesting_dept_id
    order.executing_dept_id = order_data.executing_dept_id
    order.priority = order_data.priority
    order.planned_date = order_data.planned_date
    order.comment = order_data.comment
    
    await db.execute(delete(OrderItemModel).where(OrderItemModel.order_id == order_id))
    for i in order_data.items: db.add(OrderItemModel(**i.model_dump(), order_id=order_id))
    await db.commit()
    return {"status": "success"}

@app.patch("/api/orders/{order_id}/status")
async def update_order_status(order_id: str, payload: StatusUpdateSchema, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(OrderModel).filter_by(id=order_id))
    order = res.scalars().first()
    if payload.status == 'Принят в работу' and order.status != 'Принят в работу': order.approved_at = datetime.utcnow()
    order.status = payload.status
    if payload.reject_comment: order.comment = f"{order.comment or ''}\n\n[ОТКАЗ]: {payload.reject_comment}"
    await db.commit()
    return {"status": "success"}

@app.get("/api/orders")
async def get_all_orders(db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(OrderModel).options(selectinload(OrderModel.items).selectinload(OrderItemModel.contract_items).selectinload(ContractItemModel.contract)))
    orders = res.scalars().all()
    out = []
    for o in orders:
        items_out = []
        contracts_set = {}
        for i in o.items:
            c_items_out = []
            for ci in i.contract_items:
                c_items_out.append({
                    "ordered_quantity": ci.ordered_quantity,
                    "contract_id": ci.contract_id,
                    "status": ci.contract.status,
                    "supplier": ci.contract.supplier_name
                })
                contracts_set[ci.contract_id] = ci.contract
            items_out.append({
                "id": i.id, "material_code": i.material_code, "name": i.name, "unit": i.unit,
                "requested_quantity": i.requested_quantity, "allow_analog": i.allow_analog,
                "specification": i.specification, "tech_spec_file": i.tech_spec_file,
                "contract_items": c_items_out
            })
        out.append({
            "id": o.id, "status": o.status, "enterprise": o.enterprise, "priority": o.priority,
            "requesting_dept_id": o.requesting_dept_id, "executing_dept_id": o.executing_dept_id,
            "planned_date": o.planned_date, "created_at": o.created_at.isoformat(),
            "approved_at": o.approved_at.isoformat() if o.approved_at else None, "comment": o.comment,
            "items": items_out,
            "contracts": [{"id": c.id, "contract_number": c.contract_number, "status": c.status, "supplier_name": c.supplier_name} for c in contracts_set.values()]
        })
    return out

# --- API ДОГОВОРОВ ---
@app.post("/api/contracts")
async def create_contract(data: ContractCreateSchema, db: AsyncSession = Depends(get_db)):
    total = sum(i.ordered_quantity * i.unit_price for i in data.items)
    contract = ContractModel(
        supplier_name=data.supplier_name, contract_number=data.contract_number,
        contract_date=data.contract_date, currency=data.currency, incoterms=data.incoterms, total_amount=total
    )
    affected_orders = set()
    for i in data.items:
        ci = ContractItemModel(**i.model_dump())
        contract.items.append(ci)
        
        # Находим к какому заказу относится позиция
        item_res = await db.execute(select(OrderItemModel).filter_by(id=i.order_item_id))
        o_item = item_res.scalars().first()
        if o_item: affected_orders.add(o_item.order_id)
        
    db.add(contract)
    await db.commit()
    await recalculate_orders(db, affected_orders)
    return {"status": "success"}

@app.patch("/api/contracts/{c_id}/status")
async def update_contract_status(c_id: int, payload: ContractStatusUpdateSchema, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(ContractModel).options(selectinload(ContractModel.items).selectinload(ContractItemModel.order_item)).filter_by(id=c_id))
    contract = res.scalars().first()
    contract.status = payload.status
    
    affected_orders = set(ci.order_item.order_id for ci in contract.items if ci.order_item)
    await db.commit()
    await recalculate_orders(db, affected_orders)
    return {"status": "success"}

@app.get("/api/contracts")
async def get_all_contracts(db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(ContractModel).options(selectinload(ContractModel.items).selectinload(ContractItemModel.order_item)))
    contracts = res.scalars().all()
    out = []
    for c in contracts:
        out.append({
            "id": c.id, "contract_number": c.contract_number, "contract_date": c.contract_date,
            "supplier_name": c.supplier_name, "currency": c.currency, "incoterms": c.incoterms,
            "status": c.status, "total_amount": c.total_amount,
            "items": [{
                "order_item_id": ci.order_item_id, "ordered_quantity": ci.ordered_quantity, "unit_price": ci.unit_price,
                "order_item": {"name": ci.order_item.name, "order_id": ci.order_item.order_id} if ci.order_item else None
            } for ci in c.items]
        })
    return out
