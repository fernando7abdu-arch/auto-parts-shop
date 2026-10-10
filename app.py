import streamlit as st
import psycopg2
import pandas as pd
import plotly.express as px
from datetime import datetime
import os

# ============================================================
# 1. DATABASE CONNECTION
# ============================================================
@st.cache_resource
def get_connection():
    db_url = st.secrets["DATABASE_URL"]
    return psycopg2.connect(db_url, sslmode='require')

# ============================================================
# 2. INITIALIZE DATABASE (Complete Reset)
# ============================================================
def init_db():
    conn = get_connection()
    c = conn.cursor()
    
    # Clear any broken state
    conn.rollback()
    
    # Drop ALL existing tables to start completely fresh
    c.execute("DROP TABLE IF EXISTS sales")
    c.execute("DROP TABLE IF EXISTS purchases")
    c.execute("DROP TABLE IF EXISTS inventory")
    c.execute("DROP TABLE IF EXISTS settings")
    conn.commit()
    
    # Create fresh tables with correct schema
    c.execute("""CREATE TABLE inventory (
        part_number TEXT PRIMARY KEY,
        item_name TEXT,
        car_model TEXT,
        purchase_cost REAL,
        starting_stock INTEGER,
        reorder_level INTEGER
    )""")
    conn.commit()
    
    c.execute("""CREATE TABLE purchases (
        id SERIAL PRIMARY KEY,
        date TEXT,
        part_number TEXT,
        quantity INTEGER
    )""")
    conn.commit()
    
    c.execute("""CREATE TABLE sales (
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
    conn.commit()
    
    c.execute("""CREATE TABLE settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )""")
    conn.commit()
    
    # Set default tax rate
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

def get_all_stock_df():
    conn = get_connection()
    inv = pd.read_sql_query("SELECT * FROM inventory", conn)
    if inv.empty:
        return pd.DataFrame(columns=['part_number', 'item_name', 'car_model', 'purchase_cost', 'starting_stock', 'reorder_level', 'current_stock'])
    stocks = []
    for _, row in inv.iterrows():
        stocks.append(get_current_stock(row['part_number']))
    inv['current_stock'] = stocks
    return inv

# ============================================================
# 4. APP SETUP
# ============================================================
init_db()
conn = get_connection()

st.set_page_config(page_title="Yasmin Spare Parts", page_icon="🚗", layout="wide")

# Logo and Header
col_logo, col_title = st.columns([1, 4])
with col_logo:
    if os.path.exists("logo.png"):
        st.image("logo.png", width=120)
    else:
        st.markdown("## 🚗🔧")
with col_title:
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
# PAGE 1: DASHBOARD
# ============================================================
if page == "📊 Dashboard":
    st.header("📊 Business Overview")

    total_revenue = pd.read_sql_query("SELECT COALESCE(SUM(total_revenue), 0) FROM sales", conn).iloc[0, 0]
    total_tax = pd.read_sql_query("SELECT COALESCE(SUM(tax_amount), 0) FROM sales", conn).iloc[0, 0]
    total_profit = pd.read_sql_query("SELECT COALESCE(SUM(profit_margin), 0) FROM sales", conn).iloc[0, 0]
    total_sales_count = pd.read_sql_query("SELECT COUNT(*) FROM sales", conn).iloc[0, 0]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("💵 Total Revenue", f"${total_revenue:,.2f}")
    c2.metric("🧾 Total Tax", f"${total_tax:,.2f}")
    c3.metric("📈 Net Profit", f"${total_profit:,.2f}")
    c4.metric("🧾 Total Sales", f"{total_sales_count}")

    st.markdown("---")
    st.subheader("📈 Monthly Performance")
    monthly_df = pd.read_sql_query(
        """SELECT SUBSTRING(date FROM 1 FOR 7) as month,
                  SUM(total_revenue) as revenue,
                  SUM(profit_margin) as profit
           FROM sales GROUP BY month ORDER BY month""", conn)
    if not monthly_df.empty:
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
                columns={'part_number': 'Part #', 'item_name': 'Item', 'car_model': 'Car Model',
                         'current_stock': 'Stock', 'reorder_level': 'Min Level'}), use_container_width=True)
        else:
            st.success("✅ All parts are well-stocked!")
    else:
        st.info("No inventory items yet.")

# ============================================================
# PAGE 2: INVENTORY
# ============================================================
elif page == "📦 Inventory":
    st.header("📦 Manage Inventory")

    with st.expander("➕ Add New Part", expanded=True):
        with st.form("add_part_form"):
            c1, c2 = st.columns(2)
            with c1:
                item_name = st.text_input("Item Name", placeholder="e.g., Front Brake Pad")
                part_number = st.text_input("Part Number", placeholder="e.g., BRK-104")
                car_model = st.text_input("Compatible Car Model", placeholder="e.g., Toyota Corolla 2015-2020")
            with c2:
                purchase_cost = st.number_input("Purchase Cost per Unit ($)", min_value=0.0, step=0.01)
                starting_stock = st.number_input("Starting Quantity in Stock", min_value=0, step=1)
                reorder_level = st.number_input("Reorder Level", min_value=0, step=1, value=5)

            if st.form_submit_button("Add Part to Inventory"):
                if part_number and item_name:
                    try:
                        c = conn.cursor()
                        c.execute("""INSERT INTO inventory 
                                     (part_number, item_name, car_model, purchase_cost, starting_stock, reorder_level) 
                                     VALUES (%s, %s, %s, %s, %s, %s)""",
                                  (part_number, item_name, car_model, purchase_cost, starting_stock, reorder_level))
                        conn.commit()
                        st.success(f"✅ '{item_name}' added successfully!")
                        st.rerun()
                    except psycopg2.IntegrityError:
                        conn.rollback()
                        st.error(f"❌ Part Number '{part_number}' already exists!")
                else:
                    st.error("Item Name and Part Number are required!")

    st.markdown("---")
    st.subheader("📋 Current Inventory")
    stock_df = get_all_stock_df()
    if not stock_df.empty:
        display = stock_df[['part_number', 'item_name', 'car_model', 'purchase_cost', 'current_stock', 'reorder_level']].copy()
        display['Status'] = display.apply(lambda r: "⚠️ LOW" if r['current_stock'] <= r['reorder_level'] else "✅ OK", axis=1)
        st.dataframe(display.rename(columns={
            'part_number': 'Part #', 'item_name': 'Item', 'car_model': 'Car Model',
            'purchase_cost': 'Cost', 'current_stock': 'Stock', 'reorder_level': 'Min Level'
        }), use_container_width=True)
    else:
        st.info("No parts in inventory yet. Add your first part above!")

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
            options = stock_df['part_number'] + " — " + stock_df['item_name'] + " (" + stock_df['car_model'].fillna('N/A') + ") [Stock: " + stock_df['current_stock'].astype(str) + "]"
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
# PAGE 4: RECORD SALE & RECEIPT
# ============================================================
elif page == "💰 Record Sale":
    st.header("💰 Record a Sale")
    tax_rate = get_tax_rate()
    st.info(f"📌 Current Tax Rate: **{tax_rate * 100:.1f}%** (Change in Settings)")
    stock_df = get_all_stock_df()

    if stock_df.empty:
        st.warning("⚠️ Please add parts to your inventory first!")
    else:
        with st.form("sale_form"):
            options = stock_df['part_number'] + " — " + stock_df['item_name'] + " (" + stock_df['car_model'].fillna('N/A') + ") [Stock: " + stock_df['current_stock'].astype(str) + "]"
            selected = st.selectbox("Select Part to Sell", options)
            part_num = selected.split(" — ")[0]

            car_model = stock_df[stock_df['part_number'] == part_num]['car_model'].iloc[0]
            current_stock = stock_df[stock_df['part_number'] == part_num]['current_stock'].iloc[0]
            cost_price = stock_df[stock_df['part_number'] == part_num]['purchase_cost'].iloc[0]

            c1, c2 = st.columns(2)
            with c1:
                qty = st.number_input("Quantity Sold", min_value=1, max_value=max(1, current_stock), step=1)
            with c2:
                sale_price = st.number_input("Sale Price per Unit ($)", min_value=0.0, step=0.01)

            if sale_price > 0 and qty > 0:
                prev_rev = qty * sale_price
                prev_tax = prev_rev * tax_rate
                prev_prof = prev_rev - (qty * cost_price) - prev_tax
                st.markdown(f"**Preview:** Revenue: `${prev_rev:,.2f}` | Tax: `${prev_tax:,.2f}` | Profit: `${prev_prof:,.2f}`")

            if st.form_submit_button("✅ Record Sale & Generate Receipt"):
                total_revenue = qty * sale_price
                tax_amount = total_revenue * tax_rate
                profit_margin = total_revenue - (qty * cost_price) - tax_amount

                c = conn.cursor()
                c.execute("""INSERT INTO sales 
                             (date, part_number, car_model, quantity_sold, sale_price, total_revenue, tax_amount, profit_margin)
                             VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                          (datetime.now().strftime("%Y-%m-%d %H:%M"), part_num, car_model, qty, sale_price, total_revenue, tax_amount, profit_margin))
                conn.commit()

                st.success(f"✅ Sale recorded! Remaining stock: **{get_current_stock(part_num)}**")

                st.markdown("---")
                st.subheader("🧾 Customer Receipt")
                receipt = f"""
                <div style="border:2px solid #333;padding:20px;border-radius:10px;background:#f9f9f9;font-family:monospace;max-width:400px;margin:auto;">
                    <h3 style="text-align:center;margin-bottom:5px;">YASMIN SPARE PARTS</h3>
                    <p style="text-align:center;font-size:12px;margin-top:0;">Professional Auto Parts</p>
                    <hr>
                    <p><b>Date:</b> {datetime.now().strftime("%Y-%m-%d %H:%M")}</p>
                    <p><b>Part:</b> {part_num}</p>
                    <p><b>Item:</b> {stock_df[stock_df['part_number']==part_num]['item_name'].iloc[0]}</p>
                    <p><b>Vehicle:</b> {car_model if car_model else 'N/A'}</p>
                    <hr>
                    <p>Qty: {qty} x ${sale_price:,.2f}</p>
                    <hr>
                    <p style="font-size:1.2em;"><b>TOTAL: ${total_revenue:,.2f}</b></p>
                    <p style="font-size:0.9em;color:#666;">Tax Included: ${tax_amount:,.2f}</p>
                    <hr>
                    <p style="text-align:center;font-size:12px;">Thank you for your business!</p>
                </div>
                """
                st.components.v1.html(receipt, height=420)
                st.rerun()

# ============================================================
# PAGE 5: SALES HISTORY
# ============================================================
elif page == "📜 Sales History":
    st.header("📜 Sales History")
    sales_df = pd.read_sql_query(
        """SELECT s.date, s.part_number, i.item_name, s.car_model, s.quantity_sold,
                  s.sale_price, s.total_revenue, s.profit_margin
           FROM sales s JOIN inventory i ON s.part_number = i.part_number
           ORDER BY s.id DESC""", conn)

    if sales_df.empty:
        st.info("No sales recorded yet.")
    else:
        search = st.text_input("🔍 Search by Car Model (e.g., Toyota):")
        if search:
            sales_df = sales_df[sales_df['car_model'].str.contains(search, case=False, na=False)]

        c1, c2, c3 = st.columns(3)
        c1.metric("Total Revenue", f"${sales_df['total_revenue'].sum():,.2f}")
        c2.metric("Total Tax", f"${sales_df['total_revenue'].sum() * get_tax_rate():,.2f}")
        c3.metric("Total Profit", f"${sales_df['profit_margin'].sum():,.2f}")

        st.markdown("---")
        st.dataframe(sales_df.rename(columns={
            'date': 'Date', 'part_number': 'Part #', 'item_name': 'Item',
            'car_model': 'Car Model', 'quantity_sold': 'Qty', 'sale_price': 'Price',
            'total_revenue': 'Revenue', 'profit_margin': 'Profit'
        }), use_container_width=True)

        csv = sales_df.to_csv(index=False)
        st.download_button("📥 Export to CSV", csv, "sales_history.csv", "text/csv")

# ============================================================
# PAGE 6: SETTINGS
# ============================================================
elif page == "⚙️ Settings":
    st.header("⚙️ Settings")
    st.subheader("Tax Rate")
    current_rate = get_tax_rate()
    new_rate = st.number_input("Tax Rate (as decimal)", min_value=0.0, max_value=1.0, value=current_rate, step=0.01,
                               help="e.g., 0.10 = 10%, 0.15 = 15%")
    if st.button("Save Tax Rate"):
        set_tax_rate(new_rate)
        st.success(f"✅ Tax rate updated to **{new_rate * 100:.1f}%**")
        st.rerun()

    st.markdown("---")
    st.subheader("Database Info")
    st.info("Your data is permanently stored in the cloud database (Supabase). It will not disappear when the app goes to sleep!")