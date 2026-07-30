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
# БАЗУ НЕ МЕНЯЕМ (все твои заказы на месте)
DATABASE_URL = "sqlite+aiosqlite:///./erp_orders_v6.db"

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
    requested_quantity = Column(Float, default=0.0)
    stock_balance = Column(Float, default=0.0)
    allow_analog = Column(Boolean, default=True)
    specification = Column(String, nullable=True) 
    tech_spec_file = Column(String, nullable=True)
    
    order = relationship("OrderModel", back_populates="items")
    contract_items = relationship("ContractItemModel", back_populates="order_item", cascade="all, delete-orphan")

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
    total_amount = Column(Float, default=0.0)
    
    items = relationship("ContractItemModel", back_populates="contract", cascade="all, delete-orphan")
    invoices = relationship("InvoiceModel", back_populates="contract", cascade="all, delete-orphan")

class ContractItemModel(Base):
    __tablename__ = "contract_items"
    id = Column(Integer, primary_key=True, autoincrement=True)
    contract_id = Column(Integer, ForeignKey("contracts.id"))
    order_item_id = Column(Integer, ForeignKey("order_items.id"))
    
    ordered_quantity = Column(Float, default=0.0)
    invoiced_quantity = Column(Float, default=0.0) 
    received_quantity = Column(Float, default=0.0)
    issued_quantity = Column(Float, default=0.0)
    unit_price = Column(Float, default=0.0)
    
    contract = relationship("ContractModel", back_populates="items")
    order_item = relationship("OrderItemModel", back_populates="contract_items")
    invoice_items = relationship("InvoiceItemModel", back_populates="contract_item", cascade="all, delete-orphan")

class InvoiceModel(Base):
    __tablename__ = "invoices"
    id = Column(Integer, primary_key=True, autoincrement=True)
    contract_id = Column(Integer, ForeignKey("contracts.id"))
    invoice_number = Column(String)
    invoice_date = Column(String)
    
    factura_number = Column(String, nullable=True)
    factura_date = Column(String, nullable=True)
    
    status = Column(String, default="Ожидает поставки")
    total_amount = Column(Float, default=0.0)
    
    contract = relationship("ContractModel", back_populates="invoices")
    items = relationship("InvoiceItemModel", back_populates="invoice", cascade="all, delete-orphan")

class InvoiceItemModel(Base):
    __tablename__ = "invoice_items"
    id = Column(Integer, primary_key=True, autoincrement=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"))
    contract_item_id = Column(Integer, ForeignKey("contract_items.id"))
    
    quantity = Column(Float, default=0.0)
    unit_price = Column(Float, default=0.0)
    total_price = Column(Float, default=0.0)
    
    invoice = relationship("InvoiceModel", back_populates="items")
    contract_item = relationship("ContractItemModel", back_populates="invoice_items")

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

class ContractItemActionSchema(BaseModel):
    action: str 
    qty: float

class InvoiceItemSchema(BaseModel):
    contract_item_id: int
    quantity: float

class InvoiceCreateSchema(BaseModel):
    contract_id: int
    invoice_number: str
    invoice_date: str
    items: List[InvoiceItemSchema]

class FacturaCreateSchema(BaseModel):
    factura_number: str
    factura_date: str

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

# --- УТИЛИТЫ ---
async def recalculate_orders(db: AsyncSession, order_ids: set):
    for oid in order_ids:
        res = await db.execute(select(OrderModel).options(
            selectinload(OrderModel.items).selectinload(OrderItemModel.contract_items)
        ).filter_by(id=oid))
        order = res.scalars().first()
        if not order: continue

        total_req = sum(i.requested_quantity for i in order.items)
        total_ord = 0
        total_rec = 0
        total_iss = 0

        for item in order.items:
            for ci in item.contract_items:
                total_ord += (ci.ordered_quantity or 0.0)
                total_rec += (ci.received_quantity or 0.0)
                total_iss += (ci.issued_quantity or 0.0)

        if total_req == 0: continue

        if total_iss >= total_req: order.status = "Выполнен"
        elif total_rec >= total_req: order.status = "На складе"
        elif total_rec > 0 or total_iss > 0: order.status = "Частично на складе"
        elif total_ord >= total_req: order.status = "Заказан поставщику"
        elif total_ord > 0: order.status = "В процессе закупки"
        else: order.status = "Принят в работу"

        db.add(order)
    await db.commit()

async def recalculate_contract(db: AsyncSession, contract_id: int):
    res = await db.execute(select(ContractModel).options(selectinload(ContractModel.items)).filter_by(id=contract_id))
    contract = res.scalars().first()
    if not contract: return

    tot_ord = sum((i.ordered_quantity or 0.0) for i in contract.items)
    tot_rec = sum((i.received_quantity or 0.0) for i in contract.items)
    tot_iss = sum((i.issued_quantity or 0.0) for i in contract.items)

    if tot_iss >= tot_ord: contract.status = "Выполнен"
    elif tot_rec >= tot_ord: contract.status = "На складе"
    elif tot_rec > 0 or tot_iss > 0: contract.status = "Частично исполнен"
    else: contract.status = "Заказан поставщику"
    
    db.add(contract)
    await db.commit()

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
        <div id="headerActions"></div>
    </header>

    <!-- ВКЛАДКИ -->
    <div class="bg-white border-b border-gray-200 flex px-4 shadow-sm z-0 relative overflow-x-auto">
        <button id="tabOrders" class="px-5 py-3 font-bold border-b-2 border-blue-600 text-blue-600 transition whitespace-nowrap" onclick="switchTab('orders')">Мои заказы</button>
        <button id="tabContracts" class="px-5 py-3 font-bold border-b-2 border-transparent text-gray-500 hover:text-gray-700 transition whitespace-nowrap" onclick="switchTab('contracts')">Договоры поставки</button>
        <button id="tabInvoices" class="px-5 py-3 font-bold border-b-2 border-transparent text-gray-500 hover:text-gray-700 transition flex items-center gap-2 whitespace-nowrap" onclick="switchTab('invoices')">Инвойсы и Фактуры</button>
    </div>

    <main class="flex-1 overflow-y-auto p-4" id="mainContent">
        <div class="flex items-center justify-center h-full"><p class="text-gray-500 text-center">Загрузка данных...</p></div>
    </main>

    <!-- Заказ: Создание -->
    <div id="orderModal" class="fixed inset-0 bg-black bg-opacity-50 hidden flex items-center justify-center z-50 p-4">
        <div class="bg-white p-6 rounded-xl w-full max-w-lg shadow-2xl max-h-[90vh] overflow-y-auto">
            <h2 id="orderModalTitle" class="text-lg font-bold mb-4 text-gray-800">Создание нового заказа</h2>
            <form id="orderForm" class="space-y-4">
                <div class="grid grid-cols-2 gap-3">
                    <div><label class="block text-xs font-semibold text-gray-600 mb-1">Предприятие</label><select id="enterprise" class="w-full border rounded-lg p-2 text-sm bg-white"><option value="" selected>Выберите предприятие...</option><option value="Завод №1 (Баку)">Завод №1 (Баку)</option><option value="Завод №2 (Гянджа)">Завод №2 (Гянджа)</option></select></div>
                    <div><label class="block text-xs font-semibold text-gray-600 mb-1">Приоритет</label><select id="priority" class="w-full border rounded-lg p-2 text-sm bg-white"><option value="Средний">Средний</option><option value="Высокий">Высокий</option><option value="Низкий">Низкий</option></select></div>
                </div>
                <div class="grid grid-cols-2 gap-3">
                    <div><label class="block text-xs font-semibold text-gray-600 mb-1">Заказывающий отдел</label><input type="text" id="reqDept" required class="w-full border rounded-lg p-2 text-sm" placeholder="Например: IT"></div>
                    <div><label class="block text-xs font-semibold text-gray-600 mb-1">Исполняющий отдел</label><input type="text" id="execDept" required class="w-full border rounded-lg p-2 text-sm" placeholder="Например: Закупок"></div>
                </div>
                <div class="grid grid-cols-2 gap-3">
                    <div><label class="block text-xs font-semibold text-gray-600 mb-1">Необходимая дата</label><input type="date" id="plannedDate" class="w-full border rounded-lg p-2 text-sm"></div>
                    <div><label class="block text-xs font-semibold text-gray-600 mb-1">Общий комментарий</label><textarea id="orderComment" rows="1" class="w-full border rounded-lg p-2 text-sm resize-y" placeholder="Примечания..."></textarea></div>
                </div>
                <hr class="my-3 border-gray-200">
                <div class="flex justify-between items-center mb-2">
                    <h3 class="font-bold text-sm text-gray-700">Позиции (Товары / Услуги)</h3>
                    <button type="button" onclick="addItemRow()" class="bg-blue-100 text-blue-700 hover:bg-blue-200 px-3 py-1 rounded-lg text-xs font-bold transition shadow-sm">+ Добавить позицию</button>
                </div>
                <div id="itemsContainer" class="space-y-3"></div>
                <div class="flex justify-end space-x-2 mt-5 pt-3 border-t border-gray-200">
                    <button type="button" onclick="closeModal('orderModal')" class="px-4 py-2 text-sm font-medium text-gray-600 bg-gray-100 rounded-lg hover:bg-gray-200">Отмена</button>
                    <button type="submit" class="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700">Создать заказ</button>
                </div>
            </form>
        </div>
    </div>

    <!-- Заказ: Детали -->
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

    <!-- Договор: Создание -->
    <div id="contractModal" class="fixed inset-0 bg-black bg-opacity-50 hidden flex items-center justify-center z-50 p-4">
        <div class="bg-white p-6 rounded-xl w-full max-w-3xl shadow-2xl max-h-[95vh] overflow-y-auto">
            <h2 class="text-lg font-bold mb-4 text-indigo-800">Создание нового договора поставки</h2>
            <form id="contractForm" class="space-y-4">
                <div class="bg-indigo-50 p-3 rounded-lg border border-indigo-100 grid grid-cols-3 gap-3">
                    <div><label class="block text-xs font-semibold text-gray-700 mb-1">Поставщик</label><input type="text" id="cSupName" required class="w-full border rounded p-1.5 text-sm"></div>
                    <div><label class="block text-xs font-semibold text-gray-700 mb-1">Номер договора</label><input type="text" id="cNum" required class="w-full border rounded p-1.5 text-sm"></div>
                    <div><label class="block text-xs font-semibold text-gray-700 mb-1">Дата договора</label><input type="date" id="cDate" required class="w-full border rounded p-1.5 text-sm"></div>
                    <div><label class="block text-xs font-semibold text-gray-700 mb-1">Валюта</label><select id="cCur" class="w-full border rounded p-1.5 text-sm"><option>AZN</option><option>USD</option><option>EUR</option><option>RUB</option></select></div>
                    <div><label class="block text-xs font-semibold text-gray-700 mb-1">Инкотермс</label><select id="cInco" class="w-full border rounded p-1.5 text-sm"><option>EXW</option><option>FCA</option><option>CPT</option><option>CIP</option><option>DAP</option><option>DDP</option></select></div>
                    <div><label class="block text-xs font-semibold text-gray-700 mb-1">Общая сумма</label><input type="text" id="cTotal" readonly class="w-full bg-indigo-100 border rounded p-1.5 text-sm font-bold" value="0.00"></div>
                </div>
                <div class="flex gap-2 items-end">
                    <div class="flex-1"><label class="block text-xs font-semibold text-indigo-700 mb-1">Товары из заявок:</label><select id="cAvailItems" class="w-full border rounded p-2 text-sm bg-white"></select></div>
                    <button type="button" onclick="addContractRow()" class="bg-indigo-600 text-white px-3 py-2 rounded text-sm font-bold hover:bg-indigo-700">+ Добавить</button>
                </div>
                <div id="cRowsContainer" class="space-y-2 mt-3"></div>
                <div class="flex justify-end space-x-2 mt-5 pt-3 border-t">
                    <button type="button" onclick="closeModal('contractModal')" class="px-4 py-2 text-sm font-medium bg-gray-100 rounded-lg hover:bg-gray-200">Отмена</button>
                    <button type="submit" class="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700">Сохранить договор</button>
                </div>
            </form>
        </div>
    </div>

    <!-- Договор: Детали -->
    <div id="contractDetailModal" class="fixed inset-0 bg-black bg-opacity-50 hidden flex items-center justify-center z-50 p-4">
        <div class="bg-white p-6 rounded-xl w-full max-w-3xl shadow-2xl max-h-[95vh] overflow-y-auto">
            <div class="flex justify-between items-center mb-4 border-b pb-2">
                <h2 id="conDetTitle" class="text-lg font-bold text-indigo-800">Детали договора</h2>
                <button onclick="closeModal('contractDetailModal')" class="text-gray-400 hover:text-gray-600 font-bold text-lg">&times;</button>
            </div>
            <div id="conDetBody" class="space-y-4 text-sm text-gray-700"></div>
            <div id="conDetFooter" class="mt-6 pt-3 border-t flex justify-end gap-2"></div>
        </div>
    </div>

    <!-- ИНВОЙС: Создание -->
    <div id="invoiceModal" class="fixed inset-0 bg-black bg-opacity-50 hidden flex items-center justify-center z-50 p-4">
        <div class="bg-white p-6 rounded-xl w-full max-w-2xl shadow-2xl max-h-[95vh] overflow-y-auto">
            <h2 class="text-lg font-bold mb-4 text-teal-800">Выставление Инвойса</h2>
            <form id="invoiceForm" class="space-y-4">
                <div class="bg-teal-50 p-3 rounded-lg border border-teal-100 grid grid-cols-2 gap-3">
                    <div class="col-span-2">
                        <label class="block text-xs font-semibold text-gray-700 mb-1">Основание (Договор)</label>
                        <select id="invContract" required class="w-full border rounded p-2 text-sm bg-white font-bold text-teal-900" onchange="renderInvoiceItems()"></select>
                    </div>
                    <div><label class="block text-xs font-semibold text-gray-700 mb-1">Номер Инвойса</label><input type="text" id="invNum" required class="w-full border rounded p-1.5 text-sm"></div>
                    <div><label class="block text-xs font-semibold text-gray-700 mb-1">Дата Инвойса</label><input type="date" id="invDate" required class="w-full border rounded p-1.5 text-sm"></div>
                </div>
                <h3 class="font-bold text-sm text-gray-700 border-b pb-1">Позиции для инвойсирования (Остатки по договору)</h3>
                <div id="invRowsContainer" class="space-y-2 max-h-60 overflow-y-auto pr-2"></div>
                <div class="flex justify-between items-center mt-3 pt-3 border-t">
                    <div class="font-bold text-gray-700">Сумма инвойса: <span id="invTotal" class="text-teal-700 text-lg">0.00</span></div>
                    <div class="flex gap-2">
                        <button type="button" onclick="closeModal('invoiceModal')" class="px-4 py-2 text-sm font-medium bg-gray-100 rounded-lg hover:bg-gray-200">Отмена</button>
                        <button type="submit" class="px-4 py-2 text-sm font-medium text-white bg-teal-600 rounded-lg hover:bg-teal-700 shadow-sm">Создать Инвойс</button>
                    </div>
                </div>
            </form>
        </div>
    </div>

    <!-- ФАКТУРА: Регистрация -->
    <div id="facturaModal" class="fixed inset-0 bg-black bg-opacity-50 hidden flex items-center justify-center z-50 p-4">
        <div class="bg-white p-6 rounded-xl w-full max-w-sm shadow-2xl">
            <h2 class="text-lg font-bold mb-4 text-orange-700">Регистрация Фактуры</h2>
            <p class="text-xs text-gray-600 mb-4 bg-orange-50 p-2 rounded border border-orange-100">Внимание: Регистрация фактуры автоматически оформит приход указанных в инвойсе товаров на склад.</p>
            <form id="facturaForm" class="space-y-3">
                <input type="hidden" id="facInvId">
                <div><label class="block text-xs font-semibold text-gray-700 mb-1">Номер Фактуры (Накладной)</label><input type="text" id="facNum" required class="w-full border rounded p-2 text-sm"></div>
                <div><label class="block text-xs font-semibold text-gray-700 mb-1">Дата получения</label><input type="date" id="facDate" required class="w-full border rounded p-2 text-sm"></div>
                <div class="flex justify-end space-x-2 mt-4 pt-3 border-t">
                    <button type="button" onclick="closeModal('facturaModal')" class="px-3 py-1.5 text-sm bg-gray-100 rounded hover:bg-gray-200">Отмена</button>
                    <button type="submit" class="px-3 py-1.5 text-sm text-white bg-orange-600 rounded hover:bg-orange-700 font-bold shadow-sm">Подтвердить приход</button>
                </div>
            </form>
        </div>
    </div>

    <script>
        let currentTab = 'orders';
        let ordersCache = [];
        let contractsCache = [];
        let invoicesCache = [];
        let editingOrderId = null;

        // --- УПРАВЛЕНИЕ ВКЛАДКАМИ ---
        function switchTab(tab) {
            currentTab = tab;
            document.getElementById('tabOrders').className = `px-5 py-3 font-bold transition border-b-2 ${tab === 'orders' ? 'border-blue-600 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700'} whitespace-nowrap`;
            document.getElementById('tabContracts').className = `px-5 py-3 font-bold transition border-b-2 ${tab === 'contracts' ? 'border-indigo-600 text-indigo-600' : 'border-transparent text-gray-500 hover:text-gray-700'} whitespace-nowrap`;
            document.getElementById('tabInvoices').className = `px-5 py-3 font-bold transition border-b-2 ${tab === 'invoices' ? 'border-teal-600 text-teal-600' : 'border-transparent text-gray-500 hover:text-gray-700'} flex items-center gap-2 whitespace-nowrap`;
            
            const btnContainer = document.getElementById('headerActions');
            if(tab === 'orders') {
                btnContainer.innerHTML = `<button onclick="openOrderModal()" class="bg-blue-700 hover:bg-blue-800 text-white px-3 py-1.5 rounded-lg font-medium text-sm flex items-center shadow-sm">+ Новый заказ</button>`;
            } else if(tab === 'contracts') {
                btnContainer.innerHTML = `<button onclick="openContractModal()" class="bg-indigo-600 hover:bg-indigo-700 text-white px-3 py-1.5 rounded-lg font-medium text-sm flex items-center shadow-sm">+ Создать договор</button>`;
            } else {
                btnContainer.innerHTML = `<button onclick="openInvoiceModal()" class="bg-teal-600 hover:bg-teal-700 text-white px-3 py-1.5 rounded-lg font-medium text-sm flex items-center shadow-sm">+ Создать Инвойс</button>`;
            }
            renderApp();
        }

        document.getElementById('fabAddOrder').addEventListener('click', openOrderModal);
        function closeModal(id) { document.getElementById(id).classList.add('hidden'); }

        async function fetchData() {
            try {
                const [resOrd, resCon, resInv] = await Promise.all([ fetch('/api/orders'), fetch('/api/contracts'), fetch('/api/invoices') ]);
                ordersCache = await resOrd.json();
                contractsCache = await resCon.json();
                invoicesCache = await resInv.json();
                renderApp();
            } catch (err) {
                console.error(err);
                document.getElementById('mainContent').innerHTML = '<p class="text-red-500 text-center mt-10">Ошибка загрузки. Нажмите Ctrl+F5.</p>';
            }
        }

        function renderApp() {
            const main = document.getElementById('mainContent');
            if (currentTab === 'orders') renderOrders(main);
            else if (currentTab === 'contracts') renderContracts(main);
            else renderInvoices(main);
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
            let fileBox = data && data.tech_spec_file && data.tech_spec_file !== '-' && data.tech_spec_file !== 'Не прикреплен' ? `<div class="mb-1 text-xs text-blue-700 bg-blue-50 px-2 py-1 rounded flex justify-between"><span class="c-file" data-file="${data.tech_spec_file}">${data.tech_spec_file}</span><button type="button" onclick="this.parentElement.remove()" class="text-red-500">✕</button></div>` : '';

            row.innerHTML = `
                <button type="button" onclick="this.closest('.item-row').remove()" class="absolute top-2 right-2 text-red-500 text-xs font-bold px-2 py-0.5 border border-red-200 bg-white rounded">✕ Удалить</button>
                <div class="grid grid-cols-3 gap-2 mb-2 pr-20"><div class="col-span-1"><label class="text-xs">Код</label><input type="text" class="i-code w-full border rounded p-1.5 text-xs" required value="${data?.material_code || ''}"></div><div class="col-span-2"><label class="text-xs">Наименование</label><input type="text" class="i-name w-full border rounded p-1.5 text-xs" required value="${data?.name || ''}"></div></div>
                <div class="grid grid-cols-3 gap-2 mb-2"><div><label class="text-xs">Кол-во</label><input type="number" step="any" class="i-qty w-full border rounded p-1.5 text-xs" required min="0.01" value="${data?.requested_quantity || 1}"></div><div><label class="text-xs">Ед. изм.</label><input type="text" class="i-unit w-full border rounded p-1.5 text-xs" required value="${data?.unit || 'шт'}"></div><div><label class="text-xs">Аналог</label><select class="i-analog w-full border rounded p-1.5 text-xs"><option value="true" ${data?.allow_analog===true?'selected':''}>Да</option><option value="false" ${data?.allow_analog===false?'selected':''}>Нет</option></select></div></div>
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

                itemsList.push({ material_code: row.querySelector('.i-code').value.trim() || '-', name: row.querySelector('.i-name').value.trim(), unit: row.querySelector('.i-unit').value.trim(), requested_quantity: parseFloat(row.querySelector('.i-qty').value) || 1, allow_analog: row.querySelector('.i-analog').value === 'true', specification: row.querySelector('.i-spec').value.trim() || '-', tech_spec_file: fname });
            });
            if(itemsList.length === 0) return alert('Добавьте позиции!');

            const payload = { id: editingOrderId || "", enterprise: document.getElementById('enterprise').value, requesting_dept_id: document.getElementById('reqDept').value, executing_dept_id: document.getElementById('execDept').value, priority: document.getElementById('priority').value, planned_date: document.getElementById('plannedDate').value, comment: document.getElementById('orderComment').value, items: itemsList };
            try {
                const res = await fetch(editingOrderId ? `/api/orders/${editingOrderId}` : '/api/orders', { method: editingOrderId ? 'PUT' : 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload) });
                if(res.ok) { closeModal('orderModal'); fetchData(); } else alert('Ошибка сервера');
            } catch(e) { alert('Ошибка сети'); }
        });

        function renderOrders(container) {
            if(ordersCache.length === 0) { container.innerHTML = '<p class="text-gray-500 text-center mt-10">Заказов пока нет</p>'; return; }
            let html = '<div class="space-y-4 max-w-3xl mx-auto pb-10">';
            ordersCache.forEach(o => {
                let pColor = o.priority==='Высокий'?'bg-red-100 text-red-700':'bg-gray-100 text-gray-700';
                let sColor = 'bg-gray-200';
                if(o.status==='Черновик') sColor='bg-gray-200 border border-gray-300';
                if(o.status==='На согласовании') sColor='bg-yellow-100 text-yellow-700';
                if(o.status==='Принят в работу') sColor='bg-purple-100 text-purple-700';
                if(o.status==='В процессе закупки') sColor='bg-indigo-100 text-indigo-700';
                if(o.status==='Заказан поставщику') sColor='bg-cyan-100 text-cyan-700';
                if(o.status==='Частично на складе') sColor='bg-pink-100 text-pink-700';
                if(o.status==='На складе') sColor='bg-orange-100 text-orange-700';
                if(o.status==='Выполнен') sColor='bg-green-100 text-green-700';

                let reqTotal=0, ordTotal=0, recTotal=0;
                o.items.forEach(i => { reqTotal+=i.requested_quantity; if(i.contract_items) i.contract_items.forEach(ci => { ordTotal+=(ci.ordered_quantity||0); recTotal+=(ci.received_quantity||0); }); });
                let progress = o.status!=='Черновик'&&o.status!=='На согласовании' ? `<span class="ml-2 text-xs font-bold px-1.5 py-0.5 rounded ${ordTotal>=reqTotal?'bg-green-100 text-green-700':'bg-blue-100 text-blue-700'}">Заказано: ${ordTotal}/${reqTotal}</span>` : '';
                let recBadge = recTotal > 0 && o.status!=='Выполнен' ? `<span class="ml-1 text-xs font-bold px-1.5 py-0.5 rounded bg-orange-100 text-orange-700">На складе: ${recTotal}</span>` : '';

                html += `<div onclick="openOrderDetail('${o.id}')" class="bg-white p-4 rounded-xl shadow-sm border border-gray-200 hover:border-blue-400 cursor-pointer transition"><div class="flex justify-between mb-2"><div><h3 class="font-bold text-gray-900 inline-block mr-2">Заказ #${o.id}</h3><span class="text-xs font-semibold px-2 py-0.5 rounded ${pColor}">${o.priority}</span></div><span class="text-xs font-bold px-2 py-1 rounded ${sColor}">${o.status}</span></div><p class="text-xs text-gray-500 mb-2">🏭 ${o.enterprise||'Не указ.'} | ${o.requesting_dept_id} ➔ ${o.executing_dept_id}</p><div class="text-xs flex gap-2 flex-wrap items-center mt-2 border-t pt-2">${progress} ${recBadge}</div></div>`;
            });
            container.innerHTML = html + '</div>';
        }

        function openOrderDetail(oId) {
            const o = ordersCache.find(x => x.id === oId);
            if(!o) return;
            document.getElementById('ordDetTitle').innerText = `Заказ #${o.id} (${o.status})`;
            let html = `<div class="grid grid-cols-2 gap-2 text-xs bg-gray-50 p-2 rounded mb-3"><div><b>Создан:</b> ${new Date(o.created_at).toLocaleDateString()}</div><div><b>Утвержден:</b> ${o.approved_at ? new Date(o.approved_at).toLocaleDateString() : '-'}</div></div><p><b>Направление:</b> ${o.requesting_dept_id} ➔ ${o.executing_dept_id}</p>${o.comment ? `<div class="text-xs bg-red-50 text-red-700 p-2 rounded mt-2 border-l-2 border-red-400 whitespace-pre-wrap">${o.comment}</div>` : ''}<h4 class="font-bold mt-4 mb-2">Позиции:</h4><div class="space-y-2">`;
            
            o.items.forEach(i => {
                let ordered=0, received=0, issued=0;
                if(i.contract_items) i.contract_items.forEach(ci => { ordered+=(ci.ordered_quantity||0); received+=(ci.received_quantity||0); issued+=(ci.issued_quantity||0); });
                let c_info = ordered > 0 ? `<div class="text-xs mt-1 text-gray-600 bg-gray-100 p-1.5 rounded">Заказано: <b class="text-indigo-700">${ordered}</b> | На складе: <b class="text-orange-600">${received}</b> | Выдано: <b class="text-green-700">${issued}</b></div>` : '<div class="text-gray-400 italic text-xs mt-1">Ждет закупки</div>';
                html += `<div class="border p-2 rounded bg-gray-50 text-sm relative"><div class="flex justify-between font-bold text-gray-800"><span>${i.name} <span class="text-gray-400 font-normal">(${i.material_code})</span></span><span>Запрос: ${i.requested_quantity} ${i.unit}</span></div>${c_info}</div>`;
            });
            html += '</div>';
            document.getElementById('ordDetBody').innerHTML = html;

            let footer = '';
            if(o.status === 'Черновик') footer = `<button onclick="editOrder('${o.id}')" class="px-4 py-2 bg-blue-100 text-blue-700 rounded font-bold">✏️ Изменить</button><button onclick="updateOrderStatus('${o.id}', 'На согласовании')" class="px-4 py-2 bg-yellow-500 text-white rounded font-bold">На согласование</button>`;
            else if (o.status === 'На согласовании') footer = `<button onclick="rejectOrder('${o.id}')" class="px-4 py-2 bg-red-600 text-white rounded font-bold">❌ Отказать</button><button onclick="updateOrderStatus('${o.id}', 'Принят в работу')" class="px-4 py-2 bg-purple-600 text-white rounded font-bold">Утвердить (В работу)</button>`;
            else footer = `<span class="text-sm text-gray-500 italic bg-gray-100 p-2 rounded w-full text-center">Закупка и движение оформляются через <b>Договоры и Инвойсы</b>.</span>`;
            document.getElementById('ordDetFooter').innerHTML = footer;
            document.getElementById('orderDetailModal').classList.remove('hidden');
        }

        function editOrder(oId) { closeModal('orderDetailModal'); const o = ordersCache.find(x => x.id === oId); editingOrderId = o.id; document.getElementById('orderModalTitle').innerText = `Редактирование #${o.id}`; document.getElementById('enterprise').value = o.enterprise||''; document.getElementById('priority').value = o.priority; document.getElementById('reqDept').value = o.requesting_dept_id; document.getElementById('execDept').value = o.executing_dept_id; document.getElementById('plannedDate').value = o.planned_date; document.getElementById('orderComment').value = o.comment||''; document.getElementById('itemsContainer').innerHTML = ''; o.items.forEach(i => addItemRow(i)); document.getElementById('orderModal').classList.remove('hidden'); }
        async function updateOrderStatus(id, st, comment=null) { try { await fetch(`/api/orders/${id}/status`, { method: 'PATCH', headers: {'Content-Type':'application/json'}, body: JSON.stringify({status: st, reject_comment: comment}) }); closeModal('orderDetailModal'); fetchData(); } catch(e) {} }
        function rejectOrder(id) { let reason = prompt('Причина отказа:'); if(reason) updateOrderStatus(id, 'Черновик', reason); }

        // ================= ДОГОВОРЫ =================
        function openContractModal() {
            document.getElementById('contractForm').reset();
            document.getElementById('cRowsContainer').innerHTML = '';
            document.getElementById('cTotal').value = '0.00';
            let opts = '<option value="" disabled selected>Выберите товар из утвержденных заявок...</option>';
            ordersCache.forEach(o => {
                if(o.status === 'Черновик' || o.status === 'На согласовании') return;
                o.items.forEach(i => {
                    let ord = 0;
                    if(i.contract_items) i.contract_items.forEach(c => ord += (c.ordered_quantity||0));
                    let rem = i.requested_quantity - ord;
                    if(rem > 0) opts += `<option value="${i.id}" data-max="${rem}" data-name="${i.name}" data-order="${o.id}">Заказ ${o.id} | ${i.name} (Нужно: ${rem})</option>`;
                });
            });
            document.getElementById('cAvailItems').innerHTML = opts;
            document.getElementById('contractModal').classList.remove('hidden');
        }

        function addContractRow() {
            const sel = document.getElementById('cAvailItems');
            if(!sel.value) return alert('Выберите позицию из списка!');
            const opt = sel.options[sel.selectedIndex];
            const iid = opt.value;
            if(document.querySelector(`.c-row[data-iid="${iid}"]`)) return alert('Эта позиция уже в списке!');
            const max = opt.getAttribute('data-max');
            const div = document.createElement('div');
            div.className = `c-row bg-white border border-indigo-200 p-2 rounded flex gap-2 items-center text-sm`;
            div.setAttribute('data-iid', iid);
            div.innerHTML = `<div class="flex-1 font-bold text-gray-700 bg-gray-100 px-2 py-1 rounded">${opt.getAttribute('data-order')} <span class="font-normal">| ${opt.getAttribute('data-name')}</span></div><div><span class="text-xs text-gray-500 block mb-0.5">Кол-во (макс ${max})</span><input type="number" step="any" min="0.01" class="cr-qty w-20 border rounded p-1" value="${max}" max="${max}" oninput="calcContractTotal()" required></div><div><span class="text-xs text-gray-500 block mb-0.5">Цена/шт</span><input type="number" step="0.01" class="cr-price w-24 border rounded p-1" placeholder="0.00" oninput="calcContractTotal()" required></div><div class="font-bold text-indigo-700 w-24 text-right cr-sum mt-4">0.00</div><button type="button" onclick="this.parentElement.remove(); calcContractTotal()" class="text-red-500 font-bold ml-2 mt-4 hover:bg-red-50 px-2 rounded">✕</button>`;
            document.getElementById('cRowsContainer').appendChild(div);
            sel.value = "";
        }

        function calcContractTotal() {
            let total = 0;
            document.querySelectorAll('.c-row').forEach(row => {
                const qtyInput = row.querySelector('.cr-qty');
                let max = parseFloat(qtyInput.getAttribute('max')), q = parseFloat(qtyInput.value)||0;
                if(q > max) { q = max; qtyInput.value = max; alert('Превышен остаток!'); }
                let sum = q * (parseFloat(row.querySelector('.cr-price').value)||0);
                row.querySelector('.cr-sum').innerText = sum.toFixed(2);
                total += sum;
            });
            document.getElementById('cTotal').value = total.toFixed(2);
        }

        document.getElementById('contractForm').addEventListener('submit', async(e) => {
            e.preventDefault();
            const items = [];
            document.querySelectorAll('.c-row').forEach(row => { items.push({ order_item_id: parseInt(row.getAttribute('data-iid')), ordered_quantity: parseFloat(row.querySelector('.cr-qty').value), unit_price: parseFloat(row.querySelector('.cr-price').value) }); });
            if(items.length === 0) return alert('Добавьте товары!');
            const payload = { supplier_name: document.getElementById('cSupName').value, contract_number: document.getElementById('cNum').value, contract_date: document.getElementById('cDate').value, currency: document.getElementById('cCur').value, incoterms: document.getElementById('cInco').value, items: items };
            try { const res = await fetch('/api/contracts', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload) }); if(res.ok) { closeModal('contractModal'); fetchData(); } else alert('Ошибка'); } catch(e) { alert('Ошибка сети'); }
        });

        function renderContracts(container) {
            if(contractsCache.length === 0) { container.innerHTML = '<p class="text-gray-500 text-center mt-10">Оформленных договоров пока нет</p>'; return; }
            let html = '<div class="space-y-4 max-w-3xl mx-auto pb-10">';
            contractsCache.forEach(c => {
                let sColor = c.status==='Заказан поставщику' ? 'bg-indigo-100 text-indigo-700' : (c.status==='Частично исполнен' ? 'bg-pink-100 text-pink-700' : (c.status==='На складе' ? 'bg-orange-100 text-orange-700' : 'bg-green-100 text-green-700'));
                html += `<div onclick="openContractDetail('${c.id}')" class="bg-white p-4 rounded-xl shadow-sm border border-gray-200 hover:border-indigo-400 cursor-pointer transition"><div class="flex justify-between mb-2"><h3 class="font-bold text-indigo-900">Договор №${c.contract_number} <span class="font-normal text-gray-500">от ${c.contract_date}</span></h3><span class="text-xs font-bold px-2 py-1 rounded ${sColor}">${c.status}</span></div><p class="text-sm font-medium mb-2">🏢 Поставщик: ${c.supplier_name}</p><div class="flex justify-between text-xs text-gray-600 bg-gray-50 p-2 rounded"><span>Условия: ${c.incoterms}, ${c.currency} | Позиций: ${c.items.length}</span><span class="font-bold text-sm text-gray-900">Сумма: ${c.total_amount} ${c.currency}</span></div></div>`;
            });
            container.innerHTML = html + '</div>';
        }

        function openContractDetail(cId) {
            const c = contractsCache.find(x => x.id === parseInt(cId));
            if(!c) return;
            document.getElementById('conDetTitle').innerText = `Договор №${c.contract_number} (${c.status})`;
            let html = `<div class="grid grid-cols-2 gap-2 text-sm bg-indigo-50 p-3 rounded mb-3 border border-indigo-100"><div><b>Поставщик:</b> ${c.supplier_name}</div><div><b>Дата:</b> ${c.contract_date}</div><div><b>Условия:</b> ${c.incoterms}, ${c.currency}</div><div><b>Сумма:</b> <span class="font-bold text-indigo-700 text-base">${c.total_amount} ${c.currency}</span></div></div><h4 class="font-bold mt-4 mb-2">Включенные позиции:</h4><div class="space-y-3">`;
            
            let canIssueAll = false;
            c.items.forEach(ci => {
                let remIss = (ci.received_quantity||0) - (ci.issued_quantity||0);
                if (remIss > 0) canIssueAll = true;
                let issBtn = remIss > 0 ? `<button onclick="procContractItem(${c.id}, ${ci.id}, 'issue', ${remIss})" class="text-xs bg-green-100 text-green-700 px-2 py-1 rounded hover:bg-green-200 font-bold border border-green-200 shadow-sm transition">✅ Выдать инициатору (макс ${remIss})</button>` : '';

                html += `<div class="border border-gray-200 p-3 rounded-lg bg-gray-50 flex flex-col gap-2"><div class="flex justify-between items-start"><div><span class="text-xs font-bold bg-white border px-1.5 py-0.5 rounded mr-1">Заказ #${ci.order_item?.order_id || '?'}</span><span class="font-bold text-gray-800 text-sm">${ci.order_item?.name || 'Товар'}</span></div></div><div class="flex gap-4 text-xs mt-1 bg-white p-2 rounded border border-gray-100 shadow-inner"><div class="text-center"><div class="text-gray-400 mb-0.5">В договоре</div><b class="text-indigo-700 text-sm">${ci.ordered_quantity}</b></div><div class="text-center"><div class="text-gray-400 mb-0.5">По Инвойсам</div><b class="text-teal-600 text-sm">${ci.invoiced_quantity||0}</b></div><div class="text-center"><div class="text-gray-400 mb-0.5">На складе</div><b class="text-orange-600 text-sm">${ci.received_quantity||0}</b></div><div class="text-center"><div class="text-gray-400 mb-0.5">Выдано</div><b class="text-green-700 text-sm">${ci.issued_quantity||0}</b></div></div><div class="flex gap-2 justify-end mt-1">${issBtn}</div></div>`;
            });
            html += '</div>';
            document.getElementById('conDetBody').innerHTML = html;

            let footer = '';
            if(canIssueAll) footer += `<button onclick="updateContractStatus(${c.id}, 'Выполнен')" class="px-4 py-2 bg-green-600 text-white rounded font-bold shadow-sm hover:bg-green-700">✅ Выдать всё доступное на складе</button>`;
            if(!canIssueAll && c.status === 'Выполнен') footer = `<span class="text-green-600 font-bold w-full text-center bg-green-50 p-2 rounded">Все товары выданы.</span>`;
            
            document.getElementById('conDetFooter').innerHTML = footer;
            document.getElementById('contractDetailModal').classList.remove('hidden');
        }

        async function procContractItem(cId, ciId, action, maxQty) {
            let qty = prompt(`Укажите количество для выдачи (Макс: ${maxQty}):`, maxQty);
            if(qty===null) return; qty=parseFloat(qty);
            if(isNaN(qty) || qty<=0 || qty>maxQty) return alert('Некорректное количество!');
            try { await fetch(`/api/contracts/${cId}/items/${ciId}`, { method: 'PATCH', headers: {'Content-Type':'application/json'}, body: JSON.stringify({action: action, qty: qty}) }); closeModal('contractDetailModal'); fetchData(); } catch(e) { alert('Ошибка'); }
        }

        async function updateContractStatus(cId, status) {
            try { await fetch(`/api/contracts/${cId}/status`, { method: 'PATCH', headers: {'Content-Type':'application/json'}, body: JSON.stringify({status: status}) }); closeModal('contractDetailModal'); fetchData(); } catch(e) {}
        }

        // ================= ИНВОЙСЫ И ФАКТУРЫ =================
        function openInvoiceModal() {
            document.getElementById('invoiceForm').reset();
            document.getElementById('invRowsContainer').innerHTML = '';
            document.getElementById('invTotal').innerText = '0.00';
            
            let opts = '<option value="" disabled selected>Выберите Договор...</option>';
            contractsCache.forEach(c => {
                let isFullyInvoiced = true;
                c.items.forEach(i => {
                    let invQ = i.invoiced_quantity || 0;
                    if (i.ordered_quantity > invQ) isFullyInvoiced = false;
                });
                if(!isFullyInvoiced) opts += `<option value="${c.id}" data-cur="${c.currency}">Договор №${c.contract_number} (${c.supplier_name})</option>`;
            });
            document.getElementById('invContract').innerHTML = opts;
            document.getElementById('invoiceModal').classList.remove('hidden');
        }

        function renderInvoiceItems() {
            const cId = parseInt(document.getElementById('invContract').value);
            const c = contractsCache.find(x => x.id === cId);
            const container = document.getElementById('invRowsContainer');
            container.innerHTML = '';
            if(!c) return;
            document.getElementById('invTotal').innerText = '0.00 ' + c.currency;

            c.items.forEach(ci => {
                let invQ = ci.invoiced_quantity || 0;
                let rem = ci.ordered_quantity - invQ;
                if (rem > 0) {
                    const div = document.createElement('div');
                    div.className = 'inv-row bg-white border border-teal-200 p-2 rounded flex gap-2 items-center text-sm shadow-sm';
                    div.setAttribute('data-ciid', ci.id);
                    div.innerHTML = `
                        <div class="flex-1 font-bold text-gray-700">${ci.order_item?.name || 'Товар'} <span class="font-normal text-xs text-gray-400">(${ci.unit_price} ${c.currency})</span></div>
                        <div>
                            <span class="text-xs text-gray-500 block mb-0.5">Кол-во (макс ${rem})</span>
                            <input type="number" step="any" min="0" max="${rem}" class="invr-qty w-20 border rounded p-1 text-teal-700 font-bold" value="${rem}" data-price="${ci.unit_price}" oninput="calcInvTotal()">
                        </div>
                        <div class="font-bold text-teal-800 w-24 text-right invr-sum mt-4">0.00</div>
                    `;
                    container.appendChild(div);
                }
            });
            calcInvTotal();
        }

        function calcInvTotal() {
            let total = 0;
            document.querySelectorAll('.inv-row').forEach(row => {
                const qtyInput = row.querySelector('.invr-qty');
                let max = parseFloat(qtyInput.getAttribute('max')), q = parseFloat(qtyInput.value)||0;
                if(q > max) { q = max; qtyInput.value = max; alert('Превышен остаток договора!'); }
                let p = parseFloat(qtyInput.getAttribute('data-price'))||0;
                let sum = q * p;
                row.querySelector('.invr-sum').innerText = sum.toFixed(2);
                total += sum;
            });
            const sel = document.getElementById('invContract');
            const cur = sel.options[sel.selectedIndex].getAttribute('data-cur');
            document.getElementById('invTotal').innerText = total.toFixed(2) + ' ' + cur;
        }

        document.getElementById('invoiceForm').addEventListener('submit', async(e) => {
            e.preventDefault();
            const items = [];
            document.querySelectorAll('.inv-row').forEach(row => {
                let q = parseFloat(row.querySelector('.invr-qty').value);
                if (q > 0) items.push({ contract_item_id: parseInt(row.getAttribute('data-ciid')), quantity: q });
            });
            if(items.length === 0) return alert('Укажите количество хотя бы для одного товара!');

            const payload = {
                contract_id: parseInt(document.getElementById('invContract').value),
                invoice_number: document.getElementById('invNum').value,
                invoice_date: document.getElementById('invDate').value,
                items: items
            };

            try {
                const res = await fetch('/api/invoices', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload) });
                if(res.ok) { closeModal('invoiceModal'); fetchData(); } else alert('Ошибка создания инвойса');
            } catch(e) { alert('Ошибка сети'); }
        });

        function renderInvoices(container) {
            if(invoicesCache.length === 0) { container.innerHTML = '<p class="text-gray-500 text-center mt-10">Инвойсов пока нет</p>'; return; }
            let html = '<div class="space-y-4 max-w-3xl mx-auto pb-10">';
            invoicesCache.forEach(inv => {
                let c = inv.contract;
                let isFactura = inv.status === 'Фактура получена';
                let sColor = isFactura ? 'bg-orange-100 text-orange-700' : 'bg-teal-100 text-teal-800 border border-teal-200';
                
                let facInfo = isFactura ? `<div class="mt-2 pt-2 border-t text-xs font-bold text-orange-700">🚚 Приход: Накладная №${inv.factura_number} от ${inv.factura_date} (Товары на складе)</div>` : '';
                let facBtn = !isFactura ? `<button onclick="openFacturaModal(${inv.id})" class="mt-2 w-full py-1.5 bg-orange-500 text-white rounded font-bold text-xs shadow-sm hover:bg-orange-600 transition">🧾 Зарегистрировать Фактуру (Приход на склад)</button>` : '';

                html += `
                    <div class="bg-white p-4 rounded-xl shadow-sm border border-gray-200">
                        <div class="flex justify-between items-center mb-2">
                            <h3 class="font-bold text-teal-900 text-lg">Инвойс №${inv.invoice_number}</h3>
                            <span class="text-xs font-bold px-2 py-1 rounded ${sColor}">${inv.status}</span>
                        </div>
                        <p class="text-sm text-gray-600">Дата: <b>${inv.invoice_date}</b> | По договору: <b class="text-indigo-700">№${c?.contract_number||'?'}</b> (${c?.supplier_name||'?'})</p>
                        <div class="bg-gray-50 p-2 mt-2 rounded border text-sm">
                            <ul class="list-disc pl-5 mb-2 text-xs text-gray-700">
                                ${inv.items.map(i => `<li>${i.contract_item?.order_item?.name || 'Товар'} — <b>${i.quantity} шт.</b> (${i.total_price} ${c?.currency||''})</li>`).join('')}
                            </ul>
                            <div class="text-right font-bold text-teal-800 pt-1 border-t">ИТОГО: ${inv.total_amount} ${c?.currency||''}</div>
                        </div>
                        ${facInfo}
                        ${facBtn}
                    </div>
                `;
            });
            container.innerHTML = html + '</div>';
        }

        function openFacturaModal(invId) {
            document.getElementById('facturaForm').reset();
            document.getElementById('facInvId').value = invId;
            document.getElementById('facturaModal').classList.remove('hidden');
        }

        document.getElementById('facturaForm').addEventListener('submit', async(e) => {
            e.preventDefault();
            const invId = document.getElementById('facInvId').value;
            const payload = { factura_number: document.getElementById('facNum').value, factura_date: document.getElementById('facDate').value };
            try {
                const res = await fetch(`/api/invoices/${invId}/factura`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload) });
                if(res.ok) { closeModal('facturaModal'); fetchData(); } else alert('Ошибка сохранения');
            } catch(e) { alert('Ошибка сети'); }
        });

        // Запуск
        switchTab('orders');
        fetchData(); // <-- ВАЖНО: Восстановил автозагрузку!
        window.onclick = function(e) { if(e.target.classList.contains('fixed') && e.target.classList.contains('inset-0')) e.target.classList.add('hidden'); }
    </script>
</body>
</html>
"""

@app.get("/app", response_class=HTMLResponse)
async def web_app():
    return HTMLResponse(content=HTML_CONTENT)
