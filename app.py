import streamlit as st
import psycopg2
import pandas as pd
from datetime import datetime

# ============================================================
# 1. DATABASE CONNECTION (CLOUD)
# ============================================================
@st.cache_resource
def get_connection():
    # Pulls the secret link from Streamlit Cloud
    db_url = st.secrets["DATABASE_URL"]
    # Connects to Supabase/PostgreSQL securely
    return psycopg2.connect(db_url, sslmode='require')

# ============================================================
# 2. INITIALIZE DATABASE TABLES
# ============================================================
def init_db():
    conn = get_connection()
    c = conn.cursor()

    # Inventory Table
    c.execute('''CREATE TABLE IF NOT EXISTS inventory
                 (part_number TEXT PRIMARY KEY,
                  item_name TEXT,
                  purchase_cost REAL,
                  starting_stock INTEGER,
                  reorder_level INTEGER)''')

    # Purchases Table (Using SERIAL for PostgreSQL auto-increment)
    c.execute('''CREATE TABLE IF NOT EXISTS purchases
                 (id SERIAL PRIMARY KEY,
                  date TEXT,
                  part_number TEXT,
                  quantity INTEGER)''')

    # Sales Table (Using SERIAL for PostgreSQL auto-increment)
    c.execute('''CREATE TABLE IF NOT EXISTS sales
                 (id SERIAL PRIMARY KEY,
                  date TEXT,
                  part_number TEXT,
                  quantity_sold INTEGER,
                  sale_price REAL,
                  total_revenue REAL,
                  tax_amount REAL,
                  profit_margin REAL)''')

    # Settings Table
    c.execute('''CREATE TABLE IF NOT EXISTS settings
                 (key TEXT PRIMARY KEY, value TEXT)''')
    
    # Set default tax rate if it doesn't exist
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

def set_tax_rate(rate):
    conn = get_connection()
    c = conn.cursor()
    # Note: psycopg2 uses %s for variables, not ?
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
        return pd.DataFrame(columns=['part_number', 'item_name', 'purchase_cost', 
                                      'starting_stock', 'reorder_level', 'current_stock'])
    
    stocks = []
    for _, row in inv.iterrows():
        stocks.append(get_current_stock(row['part_number']))
    inv['current_stock'] = stocks
    return inv

# ============================================================
# 4. APP INITIALIZATION & SIDEBAR
# ============================================================
# Run database setup
init_db()
# Create the main connection for the app pages
conn = get_connection()

st.set_page_config(page_title="Auto Parts Shop Manager", page_icon="🔧", layout="wide")

st.sidebar.title("🔧 Auto Parts Manager")
page = st.sidebar.radio("Navigate to:", [
    "📊 Dashboard",
    "📦 Inventory",
    "🛒 Record Purchase",
    "💰 Record Sale",
    "📜 Sales History",
    "⚙️ Settings"
])

st.title("🚗 Car Spare Parts Shop Management")
st.markdown("---")

# ============================================================
# PAGE 1: DASHBOARD
# ============================================================
if page == "📊 Dashboard":
    st.header("📊 Business Overview")

    total_revenue = pd.read_sql_query(
        "SELECT COALESCE(SUM(total_revenue), 0) as val FROM sales", conn).iloc[0, 0]
    total_tax = pd.read_sql_query(
        "SELECT COALESCE(SUM(tax_amount), 0) as val FROM sales", conn).iloc[0, 0]
    total_profit = pd.read_sql_query(
        "SELECT COALESCE(SUM(profit_margin), 0) as val FROM sales", conn).iloc[0, 0]
    total_sales_count = pd.read_sql_query(
        "SELECT COUNT(*) as val FROM sales", conn).iloc[0, 0]

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("💵 Total Revenue", f"${total_revenue:,.2f}")
    col2.metric("🧾 Total Tax Collected", f"${total_tax:,.2f}")
    col3.metric("📈 Total Net Profit", f"${total_profit:,.2f}")
    col4.metric("🧾 Total Sales", f"{total_sales_count}")

    st.markdown("---")

    st.subheader("⚠️ Low Stock Alerts")
    stock_df = get_all_stock_df()
    if stock_df.empty:
        st.info("No inventory items yet. Add parts in the Inventory tab.")
    else:
        low_stock = stock_df[stock_df['current_stock'] <= stock_df['reorder_level']]
        if low_stock.empty:
            st.success("✅ All parts are well-stocked!")
        else:
            st.warning(f"🚨 {len(low_stock)} part(s) need restocking!")
            display_cols = ['part_number', 'item_name', 'current_stock', 'reorder_level']
            st.dataframe(low_stock[display_cols].rename(columns={
                'part_number': 'Part Number', 'item_name': 'Item Name',
                'current_stock': 'Current Stock', 'reorder_level': 'Reorder Level'
            }), use_container_width=True)

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
                purchase_cost = st.number_input("Purchase Cost per Unit ($)", min_value=0.0, step=0.01)
            with col2:
                starting_stock = st.number_input("Starting Quantity in Stock", min_value=0, step=1)
                reorder_level = st.number_input("Reorder Level", min_value=0, step=1, value=5)

            submitted = st.form_submit_button("Add Part to Inventory")
            if submitted:
                if not part_number or not item_name:
                    st.error("Item Name and Part Number are required!")
                else:
                    try:
                        c = conn.cursor()
                        # Note: psycopg2 uses %s for variables
                        c.execute("INSERT INTO inventory VALUES (%s, %s, %s, %s, %s)",
                                  (part_number, item_name, purchase_cost, starting_stock, reorder_level))
                        conn.commit()
                        st.success(f"✅ '{item_name}' ({part_number}) added successfully!")
                        st.rerun()
                    except psycopg2.IntegrityError:
                        st.error(f"❌ Part Number '{part_number}' already exists!")

    st.markdown("---")
    st.subheader("📋 Current Inventory")
    stock_df = get_all_stock_df()
    if stock_df.empty:
        st.info("No parts in inventory yet.")
    else:
        display = stock_df[['part_number', 'item_name', 'purchase_cost', 
                            'current_stock', 'reorder_level']].copy()
        display['Status'] = display.apply(
            lambda r: "⚠️ LOW" if r['current_stock'] <= r['reorder_level'] else "✅ OK", axis=1)
        
        st.dataframe(display.rename(columns={
            'part_number': 'Part Number', 'item_name': 'Item Name',
            'purchase_cost': 'Cost/Unit', 'current_stock': 'Qty in Stock',
            'reorder_level': 'Reorder Level'
        }), use_container_width=True)

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
            options = stock_df['part_number'] + " — " + stock_df['item_name'] + \
                      " (Stock: " + stock_df['current_stock'].astype(str) + ")"
            selected = st.selectbox("Select Part", options)
            part_num = selected.split(" — ")[0]

            qty = st.number_input("Quantity Bought", min_value=1, step=1)

            submitted = st.form_submit_button("Record Purchase")
            if submitted:
                c = conn.cursor()
                c.execute("INSERT INTO purchases (date, part_number, quantity) VALUES (%s, %s, %s)",
                          (datetime.now().strftime("%Y-%m-%d %H:%M"), part_num, qty))
                conn.commit()
                new_stock = get_current_stock(part_num)
                st.success(f"✅ Purchase recorded! '{part_num}' now has **{new_stock}** units in stock.")
                st.rerun()

# ============================================================
# PAGE 4: RECORD SALE
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
            options = stock_df['part_number'] + " — " + stock_df['item_name'] + \
                      " (Stock: " + stock_df['current_stock'].astype(str) + ")"
            selected = st.selectbox("Select Part to Sell", options)
            part_num = selected.split(" — ")[0]

            current_stock = stock_df[stock_df['part_number'] == part_num]['current_stock'].iloc[0]
            cost_price = stock_df[stock_df['part_number'] == part_num]['purchase_cost'].iloc[0]

            col1, col2 = st.columns(2)
            with col1:
                qty = st.number_input("Quantity Sold", min_value=1, 
                                       max_value=max(1, current_stock), step=1)
            with col2:
                sale_price = st.number_input("Sale Price per Unit ($)", min_value=0.0, step=0.01)

            if sale_price > 0 and qty > 0:
                preview_revenue = qty * sale_price
                preview_tax = preview_revenue * tax_rate
                preview_profit = preview_revenue - (qty * cost_price) - preview_tax
                st.markdown(f"""
                | Metric | Amount |
                |---|---|
                | **Total Revenue** | ${preview_revenue:,.2f} |
                | **Tax Amount** ({tax_rate*100:.1f}%) | ${preview_tax:,.2f} |
                | **Profit Margin** | ${preview_profit:,.2f} |
                """)

            submitted = st.form_submit_button("✅ Record Sale")
            if submitted:
                total_revenue = qty * sale_price
                tax_amount = total_revenue * tax_rate
                profit_margin = total_revenue - (qty * cost_price) - tax_amount

                c = conn.cursor()
                c.execute("""INSERT INTO sales 
                             (date, part_number, quantity_sold, sale_price, 
                              total_revenue, tax_amount, profit_margin) 
                             VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                          (datetime.now().strftime("%Y-%m-%d %H:%M"), part_num, qty,
                           sale_price, total_revenue, tax_amount, profit_margin))
                conn.commit()

                new_stock = get_current_stock(part_num)
                st.success(f"✅ Sale recorded! Revenue: **${total_revenue:,.2f}** | "
                           f"Profit: **${profit_margin:,.2f}** | "
                           f"Remaining stock: **{new_stock}**")
                st.rerun()

# ============================================================
# PAGE 5: SALES HISTORY
# ============================================================
elif page == "📜 Sales History":
    st.header("📜 Sales History")

    sales_df = pd.read_sql_query(
        """SELECT s.id, s.date, s.part_number, i.item_name, s.quantity_sold, 
                  s.sale_price, s.total_revenue, s.tax_amount, s.profit_margin
           FROM sales s JOIN inventory i ON s.part_number = i.part_number
           ORDER BY s.id DESC""", conn)

    if sales_df.empty:
        st.info("No sales recorded yet.")
    else:
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Revenue", f"${sales_df['total_revenue'].sum():,.2f}")
        col2.metric("Total Tax", f"${sales_df['tax_amount'].sum():,.2f}")
        col3.metric("Total Profit", f"${sales_df['profit_margin'].sum():,.2f}")

        st.markdown("---")
        st.dataframe(sales_df.rename(columns={
            'id': '#', 'date': 'Date', 'part_number': 'Part #', 'item_name': 'Item',
            'quantity_sold': 'Qty', 'sale_price': 'Price/Unit',
            'total_revenue': 'Revenue', 'tax_amount': 'Tax', 'profit_margin': 'Profit'
        }), use_container_width=True)

        csv = sales_df.to_csv(index=False)
        st.download_button("📥 Export Sales to CSV", csv, "sales_history.csv", "text/csv")

# ============================================================
# PAGE 6: SETTINGS
# ============================================================
elif page == "⚙️ Settings":
    st.header("⚙️ Settings")

    st.subheader("Tax Rate")
    current_rate = get_tax_rate()
    new_rate = st.number_input(
        "Tax Rate (as decimal)", 
        min_value=0.0, max_value=1.0, 
        value=current_rate, step=0.01,
        help="e.g., 0.10 = 10%, 0.08 = 8%, 0.15 = 15%")

    if st.button("Save Tax Rate"):
        set_tax_rate(new_rate)
        st.success(f"✅ Tax rate updated to **{new_rate * 100:.1f}%**")
        st.rerun()

    st.markdown("---")
    st.subheader("Database Info")
    st.info("Your data is permanently stored in the cloud database (Supabase). "
            "It will not disappear when the app goes to sleep!")