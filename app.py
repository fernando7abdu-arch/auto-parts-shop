import streamlit as st
import psycopg2
import pandas as pd
import plotly.express as px
from datetime import datetime
import os

# ============================================================
# 1. DATABASE CONNECTION (CLOUD)
# ============================================================
@st.cache_resource
def get_connection():
    db_url = st.secrets["DATABASE_URL"]
    return psycopg2.connect(db_url, sslmode='require')

# ============================================================
# 2. INITIALIZE DATABASE TABLES
# ============================================================
def init_db():
    conn = get_connection()
    c = conn.cursor()

    # Inventory Table (with car_model)
    c.execute('''CREATE TABLE IF NOT EXISTS inventory
                 (part_number TEXT PRIMARY KEY,
                  item_name TEXT,
                  car_model TEXT,
                  purchase_cost REAL,
                  starting_stock INTEGER,
                  reorder_level INTEGER)''')
    
    # Safely add car_model column if it doesn't exist (for existing databases)
    try:
        c.execute("ALTER TABLE inventory ADD COLUMN IF NOT EXISTS car_model TEXT;")
    except:
        pass  # Ignore error if column already exists or other issues

    # Purchases Table
    c.execute('''CREATE TABLE IF NOT EXISTS purchases
                 (id SERIAL PRIMARY KEY,
                  date TEXT,
                  part_number TEXT,
                  quantity INTEGER)''')

    # Sales Table (with car_model)
    c.execute('''CREATE TABLE IF NOT EXISTS sales
                 (id SERIAL PRIMARY KEY,
                  date TEXT,
                  part_number TEXT,
                  car_model TEXT,
                  quantity_sold INTEGER,
                  sale_price REAL,
                  total_revenue REAL,
                  tax_amount REAL,
                  profit_margin REAL)''')
    
    # Safely add car_model column to sales if it doesn't exist
    try:
        c.execute("ALTER TABLE sales ADD COLUMN IF NOT EXISTS car_model TEXT;")
    except:
        pass  # Ignore error if column already exists or other issues

    # Settings Table
    c.execute('''CREATE TABLE IF NOT EXISTS settings
                 (key TEXT PRIMARY KEY, value TEXT)''')
    
    c.execute("SELECT COUNT(*) FROM settings WHERE key = 'tax_rate'")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO settings (key, value) VALUES ('tax_rate', '0.10')")
        
    conn.commit()
# ============================================================
# 3. HELPER FUNCTIONS
# ============================================================
def get_tax_rate():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key = 'tax_rate'")
    return float(c.fetchone()[0])

def get_current_stock(part_number):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT starting_stock FROM inventory WHERE part_number = %s", (part_number,))
    row = c.fetchone()
    if not row: return 0
    starting = row[0]
    
    c.execute("SELECT COALESCE(SUM(quantity), 0) FROM purchases WHERE part_number = %s", (part_number,))
    bought = c.fetchone()[0]
    
    c.execute("SELECT COALESCE(SUM(quantity_sold), 0) FROM sales WHERE part_number = %s", (part_number,))
    sold = c.fetchone()[0]
    
    return starting + bought - sold

def get_all_stock_df():
    conn = get_connection()
    inv = pd.read_sql_query("SELECT * FROM inventory", conn)
    if inv.empty:
        return pd.DataFrame(columns=['part_number', 'item_name', 'car_model', 'purchase_cost', 'starting_stock', 'reorder_level', 'current_stock'])
    
    stocks = [get_current_stock(row['part_number']) for _, row in inv.iterrows()]
    inv['current_stock'] = stocks
    return inv

# ============================================================
# 4. APP INITIALIZATION & SIDEBAR
# ============================================================
init_db()
conn = get_connection()

st.set_page_config(page_title="Yasmin Spare Parts", page_icon="🚗", layout="wide")

# LOGO AND HEADER
col1, col2 = st.columns([1, 3])
with col1:
    if os.path.exists("logo.png"):
        st.image("logo.png", width=120)
    else:
        st.markdown("### 🚗🔧") # Fallback emoji if logo isn't uploaded yet
with col2:
    st.title("Yasmin Spare Parts")
    st.markdown("*Professional Shop Management System*")

st.sidebar.title("🔧 Yasmin Manager")
page = st.sidebar.radio("Navigate to:", [
    "📊 Dashboard", "📦 Inventory", "🛒 Record Purchase", "💰 Record Sale", "📜 Sales History", "⚙️ Settings"
])
st.markdown("---")

# ============================================================
# PAGE 1: DASHBOARD (With Monthly Charts)
# ============================================================
if page == "📊 Dashboard":
    st.header("📊 Business Overview")

    total_revenue = pd.read_sql_query("SELECT COALESCE(SUM(total_revenue), 0) FROM sales", conn).iloc[0, 0]
    total_profit = pd.read_sql_query("SELECT COALESCE(SUM(profit_margin), 0) FROM sales", conn).iloc[0, 0]
    total_sales_count = pd.read_sql_query("SELECT COUNT(*) FROM sales", conn).iloc[0, 0]

    col1, col2, col3 = st.columns(3)
    col1.metric("💵 Total Revenue", f"${total_revenue:,.2f}")
    col2.metric("📈 Total Net Profit", f"${total_profit:,.2f}")
    col3.metric("🧾 Total Sales", f"{total_sales_count}")

    st.markdown("---")
    
    # MONTHLY PROFIT CHART
    st.subheader("📈 Monthly Performance")
    monthly_df = pd.read_sql_query(
        """SELECT SUBSTRING(date FROM 1 FOR 7) as month, 
                  SUM(total_revenue) as revenue, 
                  SUM(profit_margin) as profit 
           FROM sales GROUP BY month ORDER BY month DESC LIMIT 6""", conn)
    
    if not monthly_df.empty:
        monthly_df = monthly_df.iloc[::-1] # Reverse to show oldest to newest
        fig = px.bar(monthly_df, x='month', y=['revenue', 'profit'], 
                     labels={'value': 'Amount ($)', 'month': 'Month', 'variable': 'Metric'},
                     color_discrete_map={'revenue': '#4CAF50', 'profit': '#2196F3'})
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No sales data yet to show charts.")

    st.markdown("---")
    st.subheader("⚠️ Low Stock Alerts")
    stock_df = get_all_stock_df()
    if not stock_df.empty:
        low_stock = stock_df[stock_df['current_stock'] <= stock_df['reorder_level']]
        if not low_stock.empty:
            st.warning(f"🚨 {len(low_stock)} part(s) need restocking!")
            st.dataframe(low_stock[['part_number', 'item_name', 'car_model', 'current_stock', 'reorder_level']].rename(
                columns={'part_number': 'Part #', 'item_name': 'Item', 'car_model': 'Car Model', 'current_stock': 'Stock', 'reorder_level': 'Min Level'}), use_container_width=True)
        else:
            st.success("✅ All parts are well-stocked!")

# ============================================================
# PAGE 2: INVENTORY
# ============================================================
elif page == "📦 Inventory":
    st.header("📦 Manage Inventory")
    with st.expander("➕ Add New Part", expanded=True):
        with st.form("add_part_form"):
            col1, col2 = st.columns(2)
            with col1:
                item_name = st.text_input("Item Name", placeholder="e.g., Front Brake Pad")
                part_number = st.text_input("Part Number", placeholder="e.g., BRK-104")
                car_model = st.text_input("Compatible Car Model", placeholder="e.g., Toyota Corolla 2015-2020")
            with col2:
                purchase_cost = st.number_input("Purchase Cost per Unit ($)", min_value=0.0, step=0.01)
                starting_stock = st.number_input("Starting Quantity in Stock", min_value=0, step=1)
                reorder_level = st.number_input("Reorder Level", min_value=0, step=1, value=5)

            if st.form_submit_button("Add Part to Inventory"):
                if part_number and item_name:
                    try:
                        c = conn.cursor()
                        c.execute("INSERT INTO inventory VALUES (%s, %s, %s, %s, %s, %s)",
                                  (part_number, item_name, car_model, purchase_cost, starting_stock, reorder_level))
                        conn.commit()
                        st.success(f"✅ '{item_name}' added successfully!")
                        st.rerun()
                    except psycopg2.IntegrityError:
                        st.error(f"❌ Part Number '{part_number}' already exists!")
                else:
                    st.error("Item Name and Part Number are required!")

    st.markdown("---")
    st.subheader("📋 Current Inventory")
    stock_df = get_all_stock_df()
    if not stock_df.empty:
        display = stock_df[['part_number', 'item_name', 'car_model', 'purchase_cost', 'current_stock', 'reorder_level']].copy()
        display['Status'] = display.apply(lambda r: "⚠️ LOW" if r['current_stock'] <= r['reorder_level'] else "✅ OK", axis=1)
        st.dataframe(display.rename(columns={'part_number': 'Part #', 'item_name': 'Item', 'car_model': 'Car Model', 'purchase_cost': 'Cost', 'current_stock': 'Stock', 'reorder_level': 'Min Level'}), use_container_width=True)

# ============================================================
# PAGE 3: RECORD PURCHASE
# ============================================================
elif page == "🛒 Record Purchase":
    st.header("🛒 Record a Purchase (Restock)")
    stock_df = get_all_stock_df()
    if stock_df.empty:
        st.warning("⚠️ Please add parts to your inventory first!")
    else:
        with st.form("purchase_form"):
            options = stock_df['part_number'] + " — " + stock_df['item_name'] + " (" + stock_df['car_model'] + ") [Stock: " + stock_df['current_stock'].astype(str) + "]"
            selected = st.selectbox("Select Part", options)
            part_num = selected.split(" — ")[0]
            qty = st.number_input("Quantity Bought", min_value=1, step=1)
            if st.form_submit_button("Record Purchase"):
                c = conn.cursor()
                c.execute("INSERT INTO purchases (date, part_number, quantity) VALUES (%s, %s, %s)",
                          (datetime.now().strftime("%Y-%m-%d %H:%M"), part_num, qty))
                conn.commit()
                st.success(f"✅ Purchase recorded! '{part_num}' now has **{get_current_stock(part_num)}** units.")
                st.rerun()

# ============================================================
# PAGE 4: RECORD SALE & PRINT RECEIPT
# ============================================================
elif page == "💰 Record Sale":
    st.header("💰 Record a Sale")
    tax_rate = get_tax_rate()
    stock_df = get_all_stock_df()
    
    if stock_df.empty:
        st.warning("⚠️ Please add parts to your inventory first!")
    else:
        with st.form("sale_form"):
            options = stock_df['part_number'] + " — " + stock_df['item_name'] + " (" + stock_df['car_model'] + ") [Stock: " + stock_df['current_stock'].astype(str) + "]"
            selected = st.selectbox("Select Part to Sell", options)
            part_num = selected.split(" — ")[0]
            
            car_model = stock_df[stock_df['part_number'] == part_num]['car_model'].iloc[0]
            current_stock = stock_df[stock_df['part_number'] == part_num]['current_stock'].iloc[0]
            cost_price = stock_df[stock_df['part_number'] == part_num]['purchase_cost'].iloc[0]

            col1, col2 = st.columns(2)
            with col1:
                qty = st.number_input("Quantity Sold", min_value=1, max_value=max(1, current_stock), step=1)
            with col2:
                sale_price = st.number_input("Sale Price per Unit ($)", min_value=0.0, step=0.01)

            if sale_price > 0 and qty > 0:
                preview_rev = qty * sale_price
                preview_tax = preview_rev * tax_rate
                preview_prof = preview_rev - (qty * cost_price) - preview_tax
                st.markdown(f"**Preview:** Revenue: `${preview_rev:,.2f}` | Tax: `${preview_tax:,.2f}` | Profit: `${preview_prof:,.2f}`")

            if st.form_submit_button("✅ Record Sale & Generate Receipt"):
                total_revenue = qty * sale_price
                tax_amount = total_revenue * tax_rate
                profit_margin = total_revenue - (qty * cost_price) - tax_amount

                c = conn.cursor()
                c.execute("""INSERT INTO sales (date, part_number, car_model, quantity_sold, sale_price, total_revenue, tax_amount, profit_margin) 
                             VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                          (datetime.now().strftime("%Y-%m-%d %H:%M"), part_num, car_model, qty, sale_price, total_revenue, tax_amount, profit_margin))
                conn.commit()

                st.success(f"✅ Sale recorded! Remaining stock: **{get_current_stock(part_num)}**")
                
                # RECEIPT GENERATOR
                st.markdown("---")
                st.subheader("🧾 Customer Receipt")
                receipt_html = f"""
                <div style="border: 2px solid #333; padding: 20px; border-radius: 10px; background-color: #f9f9f9; font-family: monospace; max-width: 400px; margin: auto;">
                    <h3 style="text-align: center; margin-bottom: 5px;">YASMIN SPARE PARTS</h3>
                    <p style="text-align: center; font-size: 12px; margin-top: 0;">Professional Auto Parts</p>
                    <hr>
                    <p><strong>Date:</strong> {datetime.now().strftime("%Y-%m-%d %H:%M")}</p>
                    <p><strong>Part:</strong> {part_num}</p>
                    <p><strong>Vehicle:</strong> {car_model if car_model else 'N/A'}</p>
                    <hr>
                    <div style="display: flex; justify-content: space-between;"><span>Qty:</span> <span>{qty}</span></div>
                    <div style="display: flex; justify-content: space-between;"><span>Price/Unit:</span> <span>${sale_price:,.2f}</span></div>
                    <hr>
                    <div style="display: flex; justify-content: space-between; font-weight: bold; font-size: 1.1em;"><span>TOTAL:</span> <span>${total_revenue:,.2f}</span></div>
                    <div style="display: flex; justify-content: space-between; font-size: 0.9em; color: #666;"><span>Tax Included:</span> <span>${tax_amount:,.2f}</span></div>
                    <hr>
                    <p style="text-align: center; font-size: 12px;">Thank you for your business!</p>
                </div>
                <div style="text-align: center; margin-top: 15px;">
                    <button onclick="window.print()" style="padding: 10px 20px; background-color: #4CAF50; color: white; border: none; border-radius: 5px; cursor: pointer; font-size: 16px;">🖨️ Print Receipt</button>
                </div>
                """
                st.components.v1.html(receipt_html, height=400)
                st.rerun()

# ============================================================
# PAGE 5: SALES HISTORY
# ============================================================
elif page == "📜 Sales History":
    st.header("📜 Sales History")
    sales_df = pd.read_sql_query(
        """SELECT s.date, s.part_number, i.item_name, s.car_model, s.quantity_sold, s.sale_price, s.total_revenue, s.profit_margin
           FROM sales s JOIN inventory i ON s.part_number = i.part_number ORDER BY s.id DESC""", conn)
    
    if sales_df.empty:
        st.info("No sales recorded yet.")
    else:
        # Search by Car Model Feature
        search_model = st.text_input("🔍 Search by Car Model (e.g., Toyota):")
        if search_model:
            sales_df = sales_df[sales_df['car_model'].str.contains(search_model, case=False, na=False)]
            
        st.dataframe(sales_df.rename(columns={'date': 'Date', 'part_number': 'Part #', 'item_name': 'Item', 'car_model': 'Car Model', 'quantity_sold': 'Qty', 'sale_price': 'Price', 'total_revenue': 'Revenue', 'profit_margin': 'Profit'}), use_container_width=True)
        
        csv = sales_df.to_csv(index=False)
        st.download_button("📥 Export to CSV", csv, "sales_history.csv", "text/csv")

# ============================================================
# PAGE 6: SETTINGS
# ============================================================
elif page == "⚙️ Settings":
    st.header("⚙️ Settings")
    st.subheader("Tax Rate")
    current_rate = get_tax_rate()
    new_rate = st.number_input("Tax Rate (as decimal)", min_value=0.0, max_value=1.0, value=current_rate, step=0.01)
    if st.button("Save Tax Rate"):
        c = conn.cursor()
        c.execute("UPDATE settings SET value = %s WHERE key = 'tax_rate'", (str(new_rate),))
        conn.commit()
        st.success(f"✅ Tax rate updated to **{new_rate * 100:.1f}%**")
        st.rerun()