import hmac
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.express as px
import psycopg2
import psycopg2.errors
import streamlit as st

# ============================================================
# PAGE CONFIG (must be the first Streamlit call)
# ============================================================
st.set_page_config(page_title="Yasmin Spare Parts", page_icon="🚗", layout="wide")

TIMEZONE = ZoneInfo("Africa/Nairobi")


def now_str():
    return datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M")


# ============================================================
# DATABASE CONNECTION
# ============================================================
@st.cache_resource
def _connect():
    conn = psycopg2.connect(st.secrets["DATABASE_URL"], sslmode="require")
    # Autocommit: a failed statement can never leave the connection
    # stuck in an aborted transaction.
    conn.autocommit = True
    return conn


def get_connection():
    """Return a live connection, reconnecting if the old one went stale."""
    conn = _connect()
    try:
        if conn.closed:
            raise psycopg2.InterfaceError("closed")
        with conn.cursor() as c:
            c.execute("SELECT 1")
    except Exception:
        _connect.clear()
        conn = _connect()
    return conn


def execute(sql, params=None, fetch=False):
    conn = get_connection()
    with conn.cursor() as c:
        c.execute(sql, params)
        return c.fetchall() if fetch else None


def query_df(sql, params=None):
    conn = get_connection()
    with conn.cursor() as c:
        c.execute(sql, params)
        cols = [d[0] for d in c.description]
        return pd.DataFrame(c.fetchall(), columns=cols)


# ============================================================
# SETUP DATABASE (runs once per server process)
# ============================================================
@st.cache_resource
def setup_database():
    execute("""CREATE TABLE IF NOT EXISTS inventory (
        part_number TEXT PRIMARY KEY,
        item_name TEXT,
        car_model TEXT,
        purchase_cost NUMERIC(12,2),
        starting_stock INTEGER,
        reorder_level INTEGER
    )""")
    execute("""CREATE TABLE IF NOT EXISTS purchases (
        id SERIAL PRIMARY KEY,
        date TEXT,
        part_number TEXT,
        quantity INTEGER
    )""")
    execute("""CREATE TABLE IF NOT EXISTS sales (
        id SERIAL PRIMARY KEY,
        date TEXT,
        part_number TEXT,
        car_model TEXT,
        quantity_sold INTEGER,
        sale_price NUMERIC(12,2),
        total_revenue NUMERIC(12,2),
        tax_amount NUMERIC(12,2),
        profit_margin NUMERIC(12,2)
    )""")
    execute("""CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )""")

    # One-time migration of money columns from REAL (old schema) to NUMERIC
    money_columns = {
        ("inventory", "purchase_cost"),
        ("sales", "sale_price"),
        ("sales", "total_revenue"),
        ("sales", "tax_amount"),
        ("sales", "profit_margin"),
    }
    rows = execute(
        """SELECT table_name, column_name FROM information_schema.columns
           WHERE table_schema = current_schema() AND data_type = 'real'""",
        fetch=True,
    )
    for table, column in rows:
        if (table, column) in money_columns:  # whitelist, safe to interpolate
            execute(f"ALTER TABLE {table} ALTER COLUMN {column} "
                    f"TYPE NUMERIC(12,2) USING ROUND({column}::numeric, 2)")

    execute("INSERT INTO settings (key, value) VALUES ('tax_rate', '0.10') "
            "ON CONFLICT (key) DO NOTHING")
    execute("INSERT INTO settings (key, value) VALUES ('currency', '$') "
            "ON CONFLICT (key) DO NOTHING")
    return True


# ============================================================
# LOGIN (optional: set APP_PASSWORD in Streamlit secrets)
# ============================================================
def require_login():
    password = st.secrets.get("APP_PASSWORD")
    if not password or st.session_state.get("authed"):
        return

    # Show logo on login screen
    if os.path.exists("logo.png"):
        st.image("logo.png", width=200)

    st.title("Yasmin Spare Parts")
    st.markdown("*Professional Auto Parts Shop Management*")

    entered = st.text_input("Password", type="password")
    if st.button("Log in"):
        if hmac.compare_digest(entered.encode(), str(password).encode()):
            st.session_state["authed"] = True
            st.rerun()
        else:
            st.error("Wrong password.")
    st.stop()


# ============================================================
# HELPER FUNCTIONS
# ============================================================
def get_setting(key, default):
    rows = execute("SELECT value FROM settings WHERE key = %s", (key,), fetch=True)
    return rows[0][0] if rows else default


def set_setting(key, value):
    execute("INSERT INTO settings (key, value) VALUES (%s, %s) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (key, str(value)))


def get_tax_rate():
    try:
        return float(get_setting("tax_rate", "0.10"))
    except ValueError:
        return 0.10


def get_currency():
    return get_setting("currency", "$")


def flash(message, kind="success"):
    """Queue a message to show after the next rerun."""
    st.session_state["flash"] = (kind, message)


def show_flash():
    if "flash" in st.session_state:
        kind, message = st.session_state.pop("flash")
        getattr(st, kind)(message)


def get_all_inventory():
    """Inventory with current stock, in a single query."""
    return query_df("""
        SELECT i.part_number, i.item_name, i.car_model,
               i.purchase_cost::float AS purchase_cost,
               i.starting_stock, i.reorder_level,
               (i.starting_stock + COALESCE(p.qty, 0) - COALESCE(s.qty, 0))::int AS current_stock
        FROM inventory i
        LEFT JOIN (SELECT part_number, SUM(quantity) AS qty
                   FROM purchases GROUP BY part_number) p ON p.part_number = i.part_number
        LEFT JOIN (SELECT part_number, SUM(quantity_sold) AS qty
                   FROM sales GROUP BY part_number) s ON s.part_number = i.part_number
        ORDER BY i.item_name
    """)


def part_labels(inv_df):
    return {r.part_number: f"{r.part_number} — {r.item_name}" for r in inv_df.itertuples()}


def search_inventory(inv_df, text):
    """Filter inventory by part number, item name or car model (case-insensitive)."""
    text = (text or "").strip()
    if not text:
        return inv_df
    mask = (
        inv_df["part_number"].str.contains(text, case=False, na=False, regex=False)
        | inv_df["item_name"].str.contains(text, case=False, na=False, regex=False)
        | inv_df["car_model"].str.contains(text, case=False, na=False, regex=False)
    )
    return inv_df[mask]


# ============================================================
# INITIALIZE
# ============================================================
require_login()
setup_database()

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
    "⚙️ Settings",
])
if st.secrets.get("APP_PASSWORD") and st.sidebar.button("Log out"):
    st.session_state["authed"] = False
    st.rerun()

st.markdown("---")
show_flash()
cur = get_currency()


def money(x):
    return f"{cur}{float(x):,.2f}"


# ============================================================
# DASHBOARD
# ============================================================
if page == "📊 Dashboard":
    st.header("📊 Business Overview")

    totals = execute(
        "SELECT COALESCE(SUM(total_revenue), 0)::float, "
        "COALESCE(SUM(profit_margin), 0)::float, COUNT(*) FROM sales",
        fetch=True,
    )[0]

    c1, c2, c3 = st.columns(3)
    c1.metric("💵 Total Revenue", money(totals[0]))
    c2.metric("📈 Net Profit", money(totals[1]))
    c3.metric("🧾 Total Sales", f"{totals[2]}")

    daily = query_df("""
        SELECT SUBSTR(date, 1, 10) AS day,
               SUM(total_revenue)::float AS revenue,
               SUM(profit_margin)::float AS profit
        FROM sales GROUP BY 1 ORDER BY 1
    """)
    if not daily.empty:
        st.markdown("---")
        st.subheader("📅 Daily Revenue and Profit")
        fig = px.bar(daily, x="day", y=["revenue", "profit"], barmode="group",
                     labels={"day": "Date", "value": f"Amount ({cur})", "variable": ""})
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")
    st.subheader("⚠️ Low Stock Alerts")
    inv_df = get_all_inventory()
    if not inv_df.empty:
        low = inv_df[inv_df["current_stock"] <= inv_df["reorder_level"]]
        if not low.empty:
            st.warning(f"🚨 {len(low)} part(s) need restocking!")
            st.dataframe(
                low[["part_number", "item_name", "car_model", "current_stock", "reorder_level"]].rename(
                    columns={"part_number": "Part #", "item_name": "Item", "car_model": "Car Model",
                             "current_stock": "Stock", "reorder_level": "Min Level"}),
                hide_index=True)
        else:
            st.success("✅ All parts are well-stocked!")
    else:
        st.info("No parts in inventory yet.")

# ============================================================
# INVENTORY
# ============================================================
elif page == "📦 Inventory":
    st.header("📦 Manage Inventory")

    with st.form("add_part_form", clear_on_submit=True):
        st.subheader("➕ Add New Part")
        c1, c2 = st.columns(2)
        with c1:
            item_name = st.text_input("Item Name")
            part_number = st.text_input("Part Number")
            car_model = st.text_input("Car Model")
        with c2:
            purchase_cost = st.number_input(f"Purchase Cost ({cur})", min_value=0.0, step=0.01)
            starting_stock = st.number_input("Starting Stock", min_value=0, step=1)
            reorder_level = st.number_input("Reorder Level", min_value=0, step=1, value=5)

        if st.form_submit_button("Add Part"):
            part_number = part_number.strip()
            item_name = item_name.strip()
            if not (part_number and item_name):
                st.error("Part Number and Item Name are required!")
            else:
                try:
                    execute("""INSERT INTO inventory
                               (part_number, item_name, car_model, purchase_cost, starting_stock, reorder_level)
                               VALUES (%s, %s, %s, %s, %s, %s)""",
                            (part_number, item_name, car_model.strip(), purchase_cost,
                             int(starting_stock), int(reorder_level)))
                    flash(f"✅ '{item_name}' added!")
                    st.rerun()
                except psycopg2.errors.UniqueViolation:
                    st.error(f"Part number '{part_number}' already exists.")
                except Exception as e:
                    st.error(f"Error: {e}")

    st.markdown("---")
    st.subheader("📋 Current Inventory")
    inv_df = get_all_inventory()
    if inv_df.empty:
        st.info("No parts in inventory yet.")
    else:
        search = st.text_input(
            "🔍 Search inventory",
            placeholder="Part number, item name or car model...",
            key="inventory_search",
        )
        filtered = search_inventory(inv_df, search)
        st.caption(f"Showing {len(filtered)} of {len(inv_df)} parts")

        if filtered.empty:
            st.info("No parts match your search.")
        else:
            view = filtered.copy()
            view["Status"] = view.apply(
                lambda r: "⚠️ LOW" if r["current_stock"] <= r["reorder_level"] else "✅ OK", axis=1)
            st.dataframe(view.rename(columns={
                "part_number": "Part #", "item_name": "Item", "car_model": "Car Model",
                "purchase_cost": "Cost", "starting_stock": "Starting Stock",
                "current_stock": "Stock", "reorder_level": "Min Level"}),
                hide_index=True)

        st.markdown("---")
        st.subheader("✏️ Edit or Delete a Part")
        labels = part_labels(inv_df)
        chosen = st.selectbox("Select part", list(labels), format_func=labels.get, key="edit_part")
        row = inv_df[inv_df["part_number"] == chosen].iloc[0]

        with st.form(f"edit_form_{chosen}"):
            e1, e2 = st.columns(2)
            with e1:
                new_name = st.text_input("Item Name", value=row["item_name"] or "")
                new_model = st.text_input("Car Model", value=row["car_model"] or "")
            with e2:
                new_cost = st.number_input(f"Purchase Cost ({cur})", min_value=0.0, step=0.01,
                                           value=float(row["purchase_cost"] or 0))
                new_reorder = st.number_input("Reorder Level", min_value=0, step=1,
                                              value=int(row["reorder_level"] or 0))
            if st.form_submit_button("Save Changes"):
                if not new_name.strip():
                    st.error("Item Name is required!")
                else:
                    execute("""UPDATE inventory SET item_name = %s, car_model = %s,
                               purchase_cost = %s, reorder_level = %s WHERE part_number = %s""",
                            (new_name.strip(), new_model.strip(), new_cost, int(new_reorder), chosen))
                    flash(f"✅ '{chosen}' updated!")
                    st.rerun()

        history = execute(
            "SELECT (SELECT COUNT(*) FROM sales WHERE part_number = %s) + "
            "(SELECT COUNT(*) FROM purchases WHERE part_number = %s)",
            (chosen, chosen), fetch=True)[0][0]
        if history:
            st.caption("This part has sales or purchase history, so it can't be deleted.")
        else:
            confirm = st.checkbox("I want to delete this part", key=f"confirm_del_{chosen}")
            if st.button("🗑️ Delete Part", disabled=not confirm):
                execute("DELETE FROM inventory WHERE part_number = %s", (chosen,))
                flash(f"🗑️ '{chosen}' deleted.")
                st.rerun()

# ============================================================
# RECORD PURCHASE
# ============================================================
elif page == "🛒 Record Purchase":
    st.header("🛒 Record Purchase")
    inv_df = get_all_inventory()

    if inv_df.empty:
        st.warning("Add parts to inventory first!")
    else:
        labels = part_labels(inv_df)
        with st.form("purchase_form", clear_on_submit=True):
            part_num = st.selectbox("Select Part", list(labels), format_func=labels.get)
            qty = st.number_input("Quantity Bought", min_value=1, step=1)

            if st.form_submit_button("Record Purchase"):
                execute("INSERT INTO purchases (date, part_number, quantity) VALUES (%s, %s, %s)",
                        (now_str(), part_num, int(qty)))
                new_stock = int(inv_df.loc[inv_df["part_number"] == part_num, "current_stock"].iloc[0]) + int(qty)
                flash(f"✅ Purchase recorded! Stock of {part_num} is now {new_stock}.")
                st.rerun()

# ============================================================
# RECORD SALE
# ============================================================
elif page == "💰 Record Sale":
    st.header("💰 Record Sale")
    tax_rate = get_tax_rate()
    inv_df = get_all_inventory()

    if inv_df.empty:
        st.warning("Add parts to inventory first!")
    else:
        sale_search = st.text_input(
            "🔍 Search part",
            placeholder="Part number, item name or car model...",
            key="sale_search",
        )
        matches = search_inventory(inv_df, sale_search)
        if matches.empty:
            st.info("No parts match your search.")
            st.stop()
        if sale_search.strip():
            st.caption(f"{len(matches)} matching part(s)")

        labels = part_labels(matches)
        # The part picker lives OUTSIDE the form so the stock limit and
        # cost update immediately when a different part is chosen.
        part_num = st.selectbox("Select Part", list(labels), format_func=labels.get)
        row = inv_df[inv_df["part_number"] == part_num].iloc[0]
        current_stock = int(row["current_stock"])
        cost_price = float(row["purchase_cost"] or 0)

        st.caption(f"Car model: **{row['car_model'] or '—'}**  |  In stock: **{current_stock}**  |  "
                   f"Cost: **{money(cost_price)}**")

        if current_stock <= 0:
            st.error("This part is out of stock.")
        else:
            with st.form("sale_form"):
                qty = st.number_input("Quantity Sold", min_value=1, max_value=current_stock, step=1)
                sale_price = st.number_input(f"Sale Price per unit ({cur})", min_value=0.01, step=0.01)

                if st.form_submit_button("Record Sale"):
                    total_revenue = round(qty * sale_price, 2)
                    tax_amount = round(total_revenue * tax_rate, 2)
                    profit = round(total_revenue - qty * cost_price - tax_amount, 2)

                    # Single atomic statement: only inserts if enough stock
                    # is still available at this very moment.
                    inserted = execute("""
                        INSERT INTO sales
                            (date, part_number, car_model, quantity_sold, sale_price,
                             total_revenue, tax_amount, profit_margin)
                        SELECT %s, i.part_number, i.car_model, %s, %s, %s, %s, %s
                        FROM inventory i
                        WHERE i.part_number = %s
                          AND (i.starting_stock
                               + COALESCE((SELECT SUM(quantity) FROM purchases
                                           WHERE part_number = i.part_number), 0)
                               - COALESCE((SELECT SUM(quantity_sold) FROM sales
                                           WHERE part_number = i.part_number), 0)) >= %s
                        RETURNING id
                    """, (now_str(), int(qty), sale_price, total_revenue, tax_amount, profit,
                          part_num, int(qty)), fetch=True)

                    if inserted:
                        flash(f"✅ Sale recorded! Revenue: {money(total_revenue)}  |  Profit: {money(profit)}")
                        st.rerun()
                    else:
                        st.error("Not enough stock. Someone else may have just sold this part.")

# ============================================================
# SALES HISTORY
# ============================================================
elif page == "📜 Sales History":
    st.header("📜 Sales History")

    sales_df = query_df("""
        SELECT s.id, s.date, s.part_number, i.item_name, s.car_model, s.quantity_sold,
               s.sale_price::float AS sale_price, s.total_revenue::float AS total_revenue,
               s.tax_amount::float AS tax_amount, s.profit_margin::float AS profit_margin
        FROM sales s LEFT JOIN inventory i ON s.part_number = i.part_number
        ORDER BY s.id DESC
    """)

    if sales_df.empty:
        st.info("No sales yet.")
    else:
        st.dataframe(sales_df.drop(columns=["id"]).rename(columns={
            "date": "Date", "part_number": "Part #", "item_name": "Item",
            "car_model": "Car Model", "quantity_sold": "Qty", "sale_price": "Price",
            "total_revenue": "Revenue", "tax_amount": "Tax", "profit_margin": "Profit"}),
            hide_index=True)

        st.download_button("⬇️ Download CSV", sales_df.to_csv(index=False).encode("utf-8"),
                           file_name="sales_history.csv", mime="text/csv")

        st.markdown("---")
        st.subheader("↩️ Void a Sale")
        st.caption("Removes a wrongly entered sale and puts the stock back.")
        sale_labels = {
            int(r.id): f"#{r.id} — {r.date} — {r.item_name or r.part_number} × {r.quantity_sold}"
            for r in sales_df.head(100).itertuples()
        }
        sale_id = st.selectbox("Select sale (latest 100)", list(sale_labels), format_func=sale_labels.get)
        confirm = st.checkbox("I want to void this sale", key=f"confirm_void_{sale_id}")
        if st.button("Void Sale", disabled=not confirm):
            execute("DELETE FROM sales WHERE id = %s", (sale_id,))
            flash(f"↩️ Sale #{sale_id} voided.")
            st.rerun()

# ============================================================
# SETTINGS
# ============================================================
elif page == "⚙️ Settings":
    st.header("⚙️ Settings")

    current_rate = get_tax_rate()
    with st.form("settings_form"):
        new_rate = st.number_input("Tax Rate (decimal, e.g. 0.15 = 15%)", min_value=0.0,
                                   max_value=1.0, value=current_rate, step=0.01)
        new_currency = st.text_input("Currency symbol", value=cur, max_chars=5)
        st.caption("Tax is deducted from revenue when profit is calculated. "
                   "Changing the rate only affects future sales.")
        if st.form_submit_button("Save Settings"):
            set_setting("tax_rate", new_rate)
            set_setting("currency", new_currency.strip() or "$")
            flash(f"✅ Saved. Tax rate: {new_rate * 100:.1f}%")
            st.rerun()