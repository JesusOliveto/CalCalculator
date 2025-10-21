# CalCalculator

Webapp en **Streamlit** para:

- Buscar alimentos por **código de barras** (Open Food Facts).
- **Agregar manualmente** comidas (caseras o productos no listados).
- Registrar consumos y ver **kcal consumidas vs. objetivo diario**.
- Guardar datos en **Google Sheets** (`foods` y `entries`).

---

## Requisitos

- Python 3.10+
- Paquetes:
  ```
  streamlit
  gspread
  google-auth
  pandas
  requests
  ```

---

## Preparación de Google Sheets (una vez)

1. **Google Cloud Console**
   - Crear proyecto.
   - Habilitar **Google Sheets API** y **Google Drive API**.
   - Crear **Service Account** y **JSON key**.

2. **Google Sheets**
   - Crear un spreadsheet llamado **CalCalculator**.
   - Agregar dos pestañas: `foods` y `entries`.
   - Compartir el spreadsheet con el email de la **Service Account** (rol: Editor).

> La app crea/asegura encabezados si faltan.

---

## Secrets (Streamlit)

En **Settings → Secrets** pegar este TOML (ajustar con tus datos):

```toml
[gcp_service_account]
type = "service_account"
project_id = "calcalculator"
private_key_id = "TU_PRIVATE_KEY_ID"
# Opción A: con saltos \n
private_key = "-----BEGIN PRIVATE KEY-----\n...TU CLAVE...\n-----END PRIVATE KEY-----\n"
# Opción B: triple comillas (sin \n)
# private_key = """-----BEGIN PRIVATE KEY-----
# ...TU CLAVE...
# -----END PRIVATE KEY-----"""
client_email = "calcalculator-sa@calcalculator.iam.gserviceaccount.com"
client_id = "TU_CLIENT_ID"
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"

# Abrir por título (o usar SHEET_ID para abrir por ID)
SHEET_TITLE = "CalCalculator"
# SHEET_ID = "1_XXXXXXXXXXXX"  # opcional
```

---

## Correr local

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/Mac
source .venv/bin/activate

pip install -r requirements.txt
streamlit run streamlit_app.py
```

Para local, podés guardar los secrets en `~/.streamlit/secrets.toml` con el mismo contenido TOML.

---

## Despliegue (Streamlit Community Cloud)

1. Subir el repo a GitHub.
2. Deploy en streamlit.io apuntando a `streamlit_app.py`.
3. Cargar **Secrets** (TOML de arriba).
4. Abrir la app.

---

## Modelo de datos

### Hoja `foods` (encabezados)
| id | barcode | name | brand | kcal_per_100g | kcal_serving | serving_grams | created_at |
|----|---------|------|-------|---------------|--------------|---------------|------------|

- `barcode` puede quedar vacío en comidas caseras.

### Hoja `entries` (encabezados)
| id | food_id | ts_utc | grams | servings | kcal_total |
|----|---------|--------|-------|----------|------------|

- `ts_utc` se guarda en UTC; la app calcula “hoy” según `America/Argentina/Cordoba`.

---

## Uso

1. Ajustar **objetivo diario** (kcal).
2. **Buscar por código**: pegar EAN/UPC → consulta Open Food Facts → guardar y registrar consumo (gramos o porciones).
3. **Agregar manual**: crear alimentos caseros o no listados.
4. Ver **resumen del día** y exportar CSV.

> Cálculo:
> - Con `kcal_per_100g` y **gramos**: `(kcal_per_100g * gramos) / 100`
> - Con `kcal_serving` y **porciones**: `kcal_serving * porciones`

---

## Notas

- Si da “permiso denegado”, verificá que compartiste la hoja con la Service Account (Editor).
- Si no encuentra la hoja por título, usá `SHEET_ID`.
- Fuente por código de barras: **Open Food Facts**.
