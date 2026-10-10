import streamlit as st
import psycopg2
import pandas as pd
import plotly.express as px
from datetime import datetime
import os

# ============================================================
# DATABASE CONNECTION
# ============================================================
@st.cache_resource
def get_connection():
    db_url = st.secrets["DATABASE_URL"]
    return psycopg2.connect(db_url, sslmode='require')

# ============================================================
# SETUP DATABASE (Only runs once)
# ============================================================
def setup_database():
    conn = get_connection()
    c = conn.cursor()
    
    # Create tables only if they don't exist
    c.execute("""CREATE TABLE IF NOT EXISTS inventory (
        part_number TEXT PRIMARY KEY,
        item_name TEXT,
        car_model TEXT,
        purchase_cost REAL,
        starting_stock INTEGER,
        reorder_level INTEGER
    )""")
    
    c.execute("""CREATE TABLE IF NOT EXISTS purchases (
        id SERIAL PRIMARY KEY,
        date TEXT,
        part_number TEXT,
        quantity INTEGER
    )""")
    
    c.execute("""CREATE TABLE IF NOT EXISTS sales (
        id SERIAL PRIMARY KEY,
        date TEXT,
        part_number TEXT,
        car_model TEXT,
        quantity_sold INTEGER,
        sale_price REAL,
        total_revenue REAL,
        tax_amount REAL,
        profit_margin REAL
    )""")
    
    c.execute("""CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )""")
    
    # Add default tax rate if not exists
    c.execute("SELECT COUNT(*) FROM settings WHERE key = 'tax_rate'")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO settings (key, value) VALUES ('tax_rate', '0.10')")
    
    conn.commit()

# ============================================================
# HELPER FUNCTIONS
# ============================================================
def get_tax_rate():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key = 'tax_rate'")
    result = c.fetchone()
    return float(result[0]) if result else 0.10

def set_tax_rate(rate):
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE settings SET value = %s WHERE key = 'tax_rate'", (str(rate),))
    conn.commit()

def get_current_stock(part_number):
    conn = get_connection()
    c = conn.cursor()
    
    c.execute("SELECT starting_stock FROM inventory WHERE part_number = %s", (part_number,))
    row = c.fetchone()
    if not row:
        return 0
    starting = row[0]
    
    c.execute("SELECT COALESCE(SUM(quantity), 0) FROM purchases WHERE part_number = %s", (part_number,))
    bought = c.fetchone()[0]
    
    c.execute("SELECT COALESCE(SUM(quantity_sold), 0) FROM sales WHERE part_number = %s", (part_number,))
    sold = c.fetchone()[0]
    
    return starting + bought - sold

def get_all_inventory():
    conn = get_connection()
    df = pd.read_sql_query("SELECT * FROM inventory", conn)
    if df.empty:
        return df
    
    stocks = []
    for _, row in df.iterrows():
        stocks.append(get_current_stock(row['part_number']))
    df['current_stock'] = stocks
    return df

# ============================================================
# INITIALIZE
# ============================================================
setup_database()

st.set_page_config(page_title="Yasmin Spare Parts", page_icon="🚗", layout="wide")

# Header with Logo
col1, col2 = st.columns([1, 4])
with col1:
    if os.path.exists("logo.png"):
        st.image("logo.png", width=120)
    else:
        st.markdown("## 🚗🔧")
with col2:
    st.title("Yasmin Spare Parts")
    st.markdown("*Professional Auto Parts Shop Management*")

st.sidebar.title("🔧 Yasmin Manager")
page = st.sidebar.radio("Navigate to:", [
    "📊 Dashboard",
    "📦 Inventory",
    "🛒 Record Purchase",
    "💰 Record Sale",
    "📜 Sales History",
    "⚙️ Settings"
])
st.markdown("---")

# ============================================================
# DASHBOARD
# ============================================================
if page == "📊 Dashboard":
    st.header("📊 Business Overview")
    
    conn = get_connection()
    
    total_revenue = pd.read_sql_query("SELECT COALESCE(SUM(total_revenue), 0) FROM sales", conn).iloc[0, 0]
    total_profit = pd.read_sql_query("SELECT COALESCE(SUM(profit_margin), 0) FROM sales", conn).iloc[0, 0]
    total_sales = pd.read_sql_query("SELECT COUNT(*) FROM sales", conn).iloc[0, 0]
    
    c1, c2, c3 = st.columns(3)
    c1.metric("💵 Total Revenue", f"${total_revenue:,.2f}")
    c2.metric("📈 Net Profit", f"${total_profit:,.2f}")
    c3.metric("🧾 Total Sales", f"{total_sales}")
    
    st.markdown("---")
    st.subheader("⚠️ Low Stock Alerts")
    inv_df = get_all_inventory()
    if not inv_df.empty:
        low = inv_df[inv_df['current_stock'] <= inv_df['reorder_level']]
        if not low.empty:
            st.warning(f"🚨 {len(low)} part(s) need restocking!")
            st.dataframe(low[['part_number', 'item_name', 'car_model', 'current_stock', 'reorder_level']].rename(
                columns={'part_number': 'Part #', 'item_name': 'Item', 'car_model': 'Car Model',
                         'current_stock': 'Stock', 'reorder_level': 'Min Level'}))
        else:
            st.success("✅ All parts are well-stocked!")

# ============================================================
# INVENTORY
# ============================================================
elif page == "📦 Inventory":
    st.header("📦 Manage Inventory")
    
    conn = get_connection()
    
    with st.form("add_part_form"):
        st.subheader("➕ Add New Part")
        c1, c2 = st.columns(2)
        with c1:
            item_name = st.text_input("Item Name")
            part_number = st.text_input("Part Number")
            car_model = st.text_input("Car Model")
        with c2:
            purchase_cost = st.number_input("Purchase Cost ($)", min_value=0.0, step=0.01)
            starting_stock = st.number_input("Starting Stock", min_value=0, step=1)
            reorder_level = st.number_input("Reorder Level", min_value=0, step=1, value=5)
        
        if st.form_submit_button("Add Part"):
            if part_number and item_name:
                try:
                    c = conn.cursor()
                    c.execute("""INSERT INTO inventory 
                                 (part_number, item_name, car_model, purchase_cost, starting_stock, reorder_level)
                                 VALUES (%s, %s, %s, %s, %s, %s)""",
                              (part_number, item_name, car_model, purchase_cost, starting_stock, reorder_level))
                    conn.commit()
                    st.success(f"✅ '{item_name}' added!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")
            else:
                st.error("Part Number and Item Name are required!")
    
    st.markdown("---")
    st.subheader("📋 Current Inventory")
    inv_df = get_all_inventory()
    if inv_df.empty:
        st.info("No parts in inventory yet.")
    else:
        inv_df['Status'] = inv_df.apply(lambda r: "⚠️ LOW" if r['current_stock'] <= r['reorder_level'] else "✅ OK", axis=1)
        st.dataframe(inv_df.rename(columns={
            'part_number': 'Part #', 'item_name': 'Item', 'car_model': 'Car Model',
            'purchase_cost': 'Cost', 'current_stock': 'Stock', 'reorder_level': 'Min Level'
        }))

# ============================================================
# RECORD PURCHASE
# ============================================================
elif page == "🛒 Record Purchase":
    st.header("🛒 Record Purchase")
    
    conn = get_connection()
    inv_df = get_all_inventory()
    
    if inv_df.empty:
        st.warning("Add parts to inventory first!")
    else:
        with st.form("purchase_form"):
            options = inv_df['part_number'] + " — " + inv_df['item_name']
            selected = st.selectbox("Select Part", options)
            part_num = selected.split(" — ")[0]
            qty = st.number_input("Quantity Bought", min_value=1, step=1)
            
            if st.form_submit_button("Record Purchase"):
                c = conn.cursor()
                c.execute("INSERT INTO purchases (date, part_number, quantity) VALUES (%s, %s, %s)",
                          (datetime.now().strftime("%Y-%m-%d %H:%M"), part_num, qty))
                conn.commit()
                st.success(f"✅ Recorded! Stock: {get_current_stock(part_num)}")
                st.rerun()

# ============================================================
# RECORD SALE
# ============================================================
elif page == "💰 Record Sale":
    st.header("💰 Record Sale")
    
    conn = get_connection()
    tax_rate = get_tax_rate()
    inv_df = get_all_inventory()
    
    if inv_df.empty:
        st.warning("Add parts to inventory first!")
    else:
        with st.form("sale_form"):
            options = inv_df['part_number'] + " — " + inv_df['item_name']
            selected = st.selectbox("Select Part", options)
            part_num = selected.split(" — ")[0]
            
            car_model = inv_df[inv_df['part_number'] == part_num]['car_model'].iloc[0]
            current_stock = inv_df[inv_df['part_number'] == part_num]['current_stock'].iloc[0]
            cost_price = inv_df[inv_df['part_number'] == part_num]['purchase_cost'].iloc[0]
            
            qty = st.number_input("Quantity Sold", min_value=1, max_value=max(1, current_stock), step=1)
            sale_price = st.number_input("Sale Price ($)", min_value=0.0, step=0.01)
            
            if st.form_submit_button("Record Sale"):
                total_revenue = qty * sale_price
                tax_amount = total_revenue * tax_rate
                profit = total_revenue - (qty * cost_price) - tax_amount
                
                c = conn.cursor()
                c.execute("""INSERT INTO sales 
                             (date, part_number, car_model, quantity_sold, sale_price, total_revenue, tax_amount, profit_margin)
                             VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                          (datetime.now().strftime("%Y-%m-%d %H:%M"), part_num, car_model, qty, sale_price, total_revenue, tax_amount, profit))
                conn.commit()
                
                st.success(f"✅ Sale recorded! Revenue: ${total_revenue:,.2f}")
                st.rerun()

# ============================================================
# SALES HISTORY
# ============================================================
elif page == "📜 Sales History":
    st.header("📜 Sales History")
    
    conn = get_connection()
    sales_df = pd.read_sql_query("""
        SELECT s.date, s.part_number, i.item_name, s.car_model, s.quantity_sold,
               s.sale_price, s.total_revenue, s.profit_margin
        FROM sales s JOIN inventory i ON s.part_number = i.part_number
        ORDER BY s.id DESC
    """, conn)
    
    if sales_df.empty:
        st.info("No sales yet.")
    else:
        st.dataframe(sales_df.rename(columns={
            'date': 'Date', 'part_number': 'Part #', 'item_name': 'Item',
            'car_model': 'Car Model', 'quantity_sold': 'Qty', 'sale_price': 'Price',
            'total_revenue': 'Revenue', 'profit_margin': 'Profit'
        }))

# ============================================================
# SETTINGS
# ============================================================
elif page == "⚙️ Settings":
    st.header("⚙️ Settings")
    
    current_rate = get_tax_rate()
    new_rate = st.number_input("Tax Rate (decimal)", min_value=0.0, max_value=1.0, value=current_rate, step=0.01)
    
    if st.button("Save Tax Rate"):
        set_tax_rate(new_rate)
        st.success(f"✅ Tax rate: {new_rate * 100:.1f}%")
        st.rerun()