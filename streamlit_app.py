# streamlit_app.py
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# ---------------- Config básica ----------------
st.set_page_config(page_title="CalCalculator", page_icon="🍎", layout="centered")

TZ = ZoneInfo("America/Argentina/Cordoba")

# Nombre del Spreadsheet (o ID si lo agregás a secrets)
SHEET_TITLE = st.secrets.get("SHEET_TITLE", "CalCalculator")
SHEET_ID = st.secrets.get("SHEET_ID", None)  # opcional: si lo ponés, abre por ID

# Columnas esperadas
FOODS_HEADERS = [
    "id", "barcode", "name", "brand",
    "kcal_per_100g", "kcal_serving", "serving_grams", "created_at"
]
ENTRIES_HEADERS = ["id", "food_id", "ts_utc", "grams", "servings", "kcal_total"]

# ---------------- Conexión a Google Sheets ----------------
@st.cache_resource
def get_gc_and_ws():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"], scopes=scopes
    )
    gc = gspread.authorize(creds)

    # Abrir el Spreadsheet por ID (si hay) o por TÍTULO
    if SHEET_ID:
        sh = gc.open_by_key(SHEET_ID)
    else:
        try:
            sh = gc.open(SHEET_TITLE)
        except gspread.SpreadsheetNotFound:
            # Si no existe y tu SA tiene permisos, lo crea
            sh = gc.create(SHEET_TITLE)

    # Asegurar worksheets y encabezados
    def ensure_ws(name, headers):
        try:
            ws = sh.worksheet(name)
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet(name, rows=1000, cols=20)
            ws.update("A1", [headers])
        # Si la primera fila no coincide, reescribimos encabezados
        first_row = ws.row_values(1)
        if first_row != headers:
            ws.clear()
            ws.update("A1", [headers])
        return ws

    ws_foods = ensure_ws("foods", FOODS_HEADERS)
    ws_entries = ensure_ws("entries", ENTRIES_HEADERS)

    return gc, ws_foods, ws_entries

gc, ws_foods, ws_entries = get_gc_and_ws()

# ---------------- Utilidades de Sheets ----------------
@st.cache_data(ttl=15)
def read_df(ws, headers):
    recs = ws.get_all_records()
    df = pd.DataFrame(recs)
    if df.empty:
        return pd.DataFrame(columns=headers)

    # Tipado suave
    num_cols = {"id", "food_id", "kcal_per_100g", "kcal_serving", "serving_grams", "grams", "servings", "kcal_total"}
    for c in df.columns:
        if c in num_cols:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df

def write_df(ws, df):
    # Reescribe por completo la hoja con encabezados + datos
    headers = ws.row_values(1)
    if not headers:
        headers = FOODS_HEADERS if ws.title == "foods" else ENTRIES_HEADERS

    if df is None or df.empty:
        ws.clear()
        ws.update("A1", [headers])
        return

    df2 = df.reindex(columns=headers)
    values = [headers] + df2.fillna("").astype(str).values.tolist()
    ws.clear()
    ws.update("A1", values)

def next_id(df):
    if df.empty or "id" not in df.columns:
        return 1
    m = pd.to_numeric(df["id"], errors="coerce").max()
    return int(m) + 1 if pd.notna(m) else 1

def refresh_cache():
    read_df.clear()

# ---------------- Open Food Facts ----------------
def fetch_off_by_barcode(barcode: str):
    url = f"https://world.openfoodfacts.org/api/v0/product/{barcode}.json"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            return None
        data = r.json()
        if data.get("status") != 1:
            return None
        p = data.get("product", {}) or {}
        nutr = p.get("nutriments", {}) or {}

        def fnum(x):
            try:
                return float(x)
            except Exception:
                return None

        kcal_100 = fnum(nutr.get("energy-kcal_100g"))
        kcal_serv = fnum(nutr.get("energy-kcal_serving"))

        serving_grams = None
        s_txt = (p.get("serving_size") or "").lower().strip()
        if s_txt.endswith("g"):
            try:
                serving_grams = float(s_txt.replace("g", "").strip())
            except Exception:
                serving_grams = None

        return {
            "barcode": barcode,
            "name": p.get("product_name") or "Producto sin nombre",
            "brand": (p.get("brands") or "").split(",")[0].strip() or "",
            "kcal_per_100g": kcal_100,
            "kcal_serving": kcal_serv,
            "serving_grams": serving_grams,
        }
    except Exception:
        return None

# ---------------- Dominio ----------------
def upsert_food(food_dict):
    """Inserta/actualiza alimento por barcode (si viene). Para caseros, barcode puede ser ""."""
    foods = read_df(ws_foods, FOODS_HEADERS).copy()
    now_iso = datetime.now(tz=TZ).isoformat()

    row_idx = None
    bcode = (food_dict.get("barcode") or "").strip()
    if bcode:
        mask = foods["barcode"].fillna("") == bcode
        if mask.any():
            row_idx = foods[mask].index[0]

    if row_idx is not None:
        # Update existente
        for k, v in food_dict.items():
            foods.at[row_idx, k] = v
        if "created_at" not in foods.columns or pd.isna(foods.at[row_idx, "created_at"]):
            foods.at[row_idx, "created_at"] = now_iso
        food_id = int(foods.at[row_idx, "id"])
    else:
        # Insert nuevo
        food_id = next_id(foods)
        new = {
            "id": food_id,
            "barcode": bcode,
            "name": food_dict.get("name") or "",
            "brand": food_dict.get("brand") or "",
            "kcal_per_100g": food_dict.get("kcal_per_100g"),
            "kcal_serving": food_dict.get("kcal_serving"),
            "serving_grams": food_dict.get("serving_grams"),
            "created_at": now_iso,
        }
        foods = pd.concat([foods, pd.DataFrame([new])], ignore_index=True)

    write_df(ws_foods, foods)
    refresh_cache()
    return food_id

def add_entry(food_id, grams=None, servings=None, kcal_total=None):
    entries = read_df(ws_entries, ENTRIES_HEADERS).copy()
    entry_id = next_id(entries)
    ts_utc = datetime.utcnow().isoformat() + "Z"
    new = {
        "id": entry_id,
        "food_id": int(food_id),
        "ts_utc": ts_utc,
        "grams": grams,
        "servings": servings,
        "kcal_total": kcal_total,
    }
    entries = pd.concat([entries, pd.DataFrame([new])], ignore_index=True)
    write_df(ws_entries, entries)
    refresh_cache()
    return entry_id

def kcal_from(food_row_or_dict, grams=None, servings=None):
    # food_row_or_dict puede venir como dict (OFF) o fila de foods
    kcal_100 = food_row_or_dict.get("kcal_per_100g")
    kcal_serv = food_row_or_dict.get("kcal_serving")
    if grams and pd.notna(kcal_100):
        return (float(kcal_100) * float(grams)) / 100.0
    if servings and pd.notna(kcal_serv):
        return float(kcal_serv) * float(servings)
    if grams and pd.notna(kcal_100):
        return (float(kcal_100) * float(grams)) / 100.0
    return None

def today_entries_df():
    foods = read_df(ws_foods, FOODS_HEADERS)
    entries = read_df(ws_entries, ENTRIES_HEADERS)
    if entries.empty:
        return pd.DataFrame(columns=["Hora", "Alimento", "Marca", "Gramos", "Porciones", "kcal"])

    # Filtrar por día local
    dt_utc = pd.to_datetime(entries["ts_utc"], errors="coerce", utc=True)
    dt_local = dt_utc.dt.tz_convert(TZ)
    now = datetime.now(tz=TZ)
    start = datetime(now.year, now.month, now.day, tzinfo=TZ)
    end = start + timedelta(days=1)
    mask = (dt_local >= start) & (dt_local < end)
    today = entries.loc[mask].copy()
    if today.empty:
        return pd.DataFrame(columns=["Hora", "Alimento", "Marca", "Gramos", "Porciones", "kcal"])

    merged = today.merge(foods, left_on="food_id", right_on="id", how="left", suffixes=("_e", "_f"))
    rows = pd.DataFrame({
        "Hora": pd.to_datetime(merged["ts_utc"], utc=True).dt.tz_convert(TZ).dt.strftime("%H:%M"),
        "Alimento": merged["name"].fillna("—"),
        "Marca": merged["brand"].fillna("—"),
        "Gramos": merged["grams"],
        "Porciones": merged["servings"],
        "kcal": merged["kcal_total"],
    })
    return rows

# ---------------- UI ----------------
st.title("🍎 CalCalculator")
st.caption("Buscar por código de barras, agregar comidas caseras y descontar del objetivo diario (Google Sheets).")

# Objetivo diario en sesión (rápido de probar)
if "kcal_goal" not in st.session_state:
    st.session_state.kcal_goal = 1610
st.session_state.kcal_goal = st.number_input("Objetivo diario (kcal)", 200, 10000, st.session_state.kcal_goal, 10)

tab1, tab2, tab3 = st.tabs(["🔍 Buscar por código", "✍️ Agregar comida manual", "📜 Hoy"])

with tab1:
    with st.form("form_barcode"):
        barcode = st.text_input("Código de barras (EAN-13/UPC)", placeholder="7791234567890")
        submitted = st.form_submit_button("Buscar")
    if submitted and barcode.strip():
        info = fetch_off_by_barcode(barcode.strip())
        if not info:
            st.warning("No se encontró en Open Food Facts. Cargalo manualmente en la otra pestaña.")
        else:
            st.success(f"Encontrado: {info['name']} - {info.get('brand') or '—'}")
            st.write(
                f"**kcal/100g**: {info.get('kcal_per_100g') or '—'}  |  "
                f"**kcal/porción**: {info.get('kcal_serving') or '—'}  |  "
                f"**porción (g)**: {info.get('serving_grams') or '—'}"
            )
            food_id = upsert_food(info)
            st.info("Producto guardado en Google Sheets.")
            # Registrar consumo
            st.subheader("Registrar consumo")
            c1, c2 = st.columns(2)
            grams = c1.number_input("Gramos", min_value=0.0, step=10.0, key="grams_bar")
            servings = c2.number_input("Porciones", min_value=0.0, step=0.5, key="serv_bar")
            if st.button("Agregar entrada"):
                kcal = kcal_from(info,
                                 grams=grams if grams > 0 else None,
                                 servings=servings if servings > 0 else None)
                if kcal is None:
                    st.error("Ingresá gramos (si hay kcal/100g) o porciones (si hay kcal/porción).")
                else:
                    add_entry(food_id, grams=grams or None, servings=servings or None, kcal_total=kcal)
                    st.success(f"Entrada agregada (+{kcal:.0f} kcal).")

with tab2:
    st.write("Cargá tus comidas caseras o productos que no están en la base.")
    with st.form("form_manual"):
        name = st.text_input("Nombre", placeholder="Empanada casera de carne")
        brand = st.text_input("Marca (opcional)")
        barcode_m = st.text_input("Código de barras (opcional si casero)")
        c1, c2, c3 = st.columns(3)
        kcal_100 = c1.number_input("kcal / 100 g", min_value=0.0, step=1.0)
        kcal_serv = c2.number_input("kcal / porción", min_value=0.0, step=1.0)
        serv_g = c3.number_input("Tamaño porción (g)", min_value=0.0, step=5.0)
        ok = st.form_submit_button("Guardar alimento")
    if ok:
        if not name.strip():
            st.error("Ingresá al menos el nombre.")
        else:
            fid = upsert_food({
                "barcode": (barcode_m or "").strip(),
                "name": name.strip(),
                "brand": (brand or "").strip(),
                "kcal_per_100g": float(kcal_100) if kcal_100 else None,
                "kcal_serving": float(kcal_serv) if kcal_serv else None,
                "serving_grams": float(serv_g) if serv_g else None,
            })
            st.success(f"Alimento guardado (id {fid}).")
            with st.expander("Registrar consumo ahora"):
                c1, c2 = st.columns(2)
                grams2 = c1.number_input("Gramos", min_value=0.0, step=10.0, key="grams_manual")
                serv2 = c2.number_input("Porciones", min_value=0.0, step=0.5, key="serv_manual")
                if st.button("Agregar entrada (manual)"):
                    foods_df = read_df(ws_foods, FOODS_HEADERS)
                    food = foods_df.loc[foods_df["id"] == fid].to_dict(orient="records")[0]
                    kcal = kcal_from(food, grams=grams2 or None, servings=serv2 or None)
                    if kcal is None:
                        st.error("No se puede calcular kcal con los datos ingresados.")
                    else:
                        add_entry(fid, grams=grams2 or None, servings=serv2 or None, kcal_total=kcal)
                        st.success(f"Entrada agregada (+{kcal:.0f} kcal).")

with tab3:
    df = today_entries_df()
    total = float(df["kcal"].fillna(0).sum()) if not df.empty else 0.0
    remaining = st.session_state.kcal_goal - total
    c1, c2 = st.columns(2)
    c1.metric("Consumido hoy", f"{total:.0f} kcal")
    c2.metric("Restante hoy", f"{remaining:.0f} kcal")

    if not df.empty:
        st.dataframe(df, use_container_width=True)
        st.download_button("Exportar CSV (hoy)", df.to_csv(index=False).encode("utf-8"),
                           "consumos_hoy.csv", "text/csv")

st.divider()
st.caption("Tip: En web, el escaneo con cámara se puede sumar luego con un componente JS (QuaggaJS/ZXing).")
