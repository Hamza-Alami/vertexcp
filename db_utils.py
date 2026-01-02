import pandas as pd
import streamlit as st
import requests
import certifi
import urllib3
from bs4 import BeautifulSoup
from db_connection import get_supabase_client
from datetime import date, datetime
from typing import Optional

##################################################
#            Supabase Client & Helpers
##################################################

def get_supabase():
    """Return the Supabase client from a global connection."""
    return get_supabase_client()

def client_table():
    """Shortcut to the 'clients' table."""
    return get_supabase().table("clients")

def portfolio_table():
    """Shortcut to the 'portfolios' table."""
    return get_supabase().table("portfolios")

def performance_table():
    """Shortcut to the 'performance_periods' table."""
    return get_supabase().table("performance_periods")

def prices_table():
    """Shortcut to the 'market_prices' table (valeur, cours, updated_at)."""
    return get_supabase().table("market_prices")

##################################################
#               MASI Fetch
##################################################

# Disable warnings if we need to fall back to verify=False
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def fetch_masi_from_cb() -> float:
    """
    Fetch MASI index from Casablanca Bourse API.
    Tries with SSL verification first; if it fails, retries without verification.
    """
    url = "https://www.casablanca-bourse.com/api/proxy/fr/api/bourse/dashboard/grouped_index_watch?"

    for verify_mode in (certifi.where(), False):  # secure first, then fallback
        try:
            r = requests.get(url, timeout=10, verify=verify_mode)
            r.raise_for_status()
            data = r.json()

            for block in data.get("data", []):
                title = (block.get("title") or "").strip().lower()
                if "principaux" in title and "indice" in title:
                    for item in block.get("items", []):
                        if (item.get("index") or "").strip().upper() == "MASI":
                            val_str = str(item.get("field_index_value", "0"))
                            val_str = val_str.replace(" ", "").replace(",", ".")
                            try:
                                return float(val_str)
                            except ValueError:
                                return 0.0
            return 0.0

        except Exception as e:
            if verify_mode is False:
                st.error(f"❌ Still cannot fetch MASI index: {e}")
                return 0.0
            continue

##################################################
#       Fetching Stocks (Scrape + Supabase Cache)
##################################################

CB_MARKET_URL = "https://www.casablanca-bourse.com/fr/live-market/marche-actions-groupement"

# Freshness logic:
# - Streamlit cache: 60s
# - Supabase cached prices considered fresh for: 180s
SUPABASE_PRICES_MAX_AGE_SECONDS = 180

def _parse_float_fr(x: str) -> float:
    if x is None:
        return 0.0
    s = str(x).strip()
    if s in ("", "-", "—"):
        return 0.0
    s = s.replace("\xa0", " ").replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0

def _scrape_cb_prices() -> pd.DataFrame:
    """
    Scrape Casablanca Bourse Live Market page and return DataFrame: [valeur, cours]
    Always appends Cash (cours=1.0)
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Streamlit; IDBourse) AppleWebKit/537.36 (KHTML, like Gecko) Chrome Safari"
    }

    # Try SSL verified first, then fallback
    last_err: Optional[Exception] = None
    for verify_mode in (certifi.where(), False):
        try:
            r = requests.get(
                CB_MARKET_URL,
                timeout=20,
                headers=headers,
                verify=verify_mode,
            )
            r.raise_for_status()
            html = r.text
            break
        except Exception as e:
            last_err = e
            if verify_mode is False:
                raise
            continue
    else:
        raise last_err or RuntimeError("Unknown scraping error")

    soup = BeautifulSoup(html, "lxml")
    tables = soup.find_all("table")

    rows = []
    for table in tables:
        tbody = table.find("tbody")
        if not tbody:
            continue

        thead = table.find("thead")
        header_cells = []
        if thead:
            header_cells = [th.get_text(" ", strip=True).lower() for th in thead.find_all("th")]

        # Locate "Dernier cours" column if present
        last_price_idx = None
        for i, h in enumerate(header_cells):
            if ("dernier" in h and "cours" in h) or (h.strip() == "dernier"):
                last_price_idx = i
                break

        for tr in tbody.find_all("tr"):
            tds = tr.find_all("td")
            if not tds:
                continue

            name = tds[0].get_text(" ", strip=True)
            if not name:
                continue

            if last_price_idx is not None and last_price_idx < len(tds):
                last_price_txt = tds[last_price_idx].get_text(" ", strip=True)
            else:
                # Fallback to common layout (index 4)
                last_price_txt = tds[4].get_text(" ", strip=True) if len(tds) > 4 else "0"

            price = _parse_float_fr(last_price_txt)
            rows.append({"valeur": name, "cours": price})

    df = pd.DataFrame(rows).drop_duplicates(subset=["valeur"], keep="last")
    if df.empty:
        df = pd.DataFrame(columns=["valeur", "cours"])

    # Always include Cash
    df = pd.concat([df, pd.DataFrame([{"valeur": "Cash", "cours": 1.0}])], ignore_index=True)
    return df[["valeur", "cours"]]

def _read_prices_from_supabase(max_age_seconds: int = SUPABASE_PRICES_MAX_AGE_SECONDS) -> pd.DataFrame:
    """
    Read cached market prices from Supabase table market_prices.
    Returns empty DF if:
      - table is empty
      - updated_at is too old
      - any error occurs
    """
    try:
        res = prices_table().select("*").execute()
        if not res.data:
            return pd.DataFrame()

        df = pd.DataFrame(res.data)
        if df.empty or "updated_at" not in df.columns or "valeur" not in df.columns or "cours" not in df.columns:
            return pd.DataFrame()

        df["updated_at"] = pd.to_datetime(df["updated_at"], errors="coerce", utc=True)
        newest = df["updated_at"].max()
        if pd.isna(newest):
            return pd.DataFrame()

        now_utc = pd.Timestamp.utcnow().tz_localize("UTC")
        age = (now_utc - newest).total_seconds()
        if age > max_age_seconds:
            return pd.DataFrame()

        # Convert cours to float safely
        df["cours"] = df["cours"].apply(lambda x: float(x) if x is not None else 0.0)

        out = df[["valeur", "cours"]].copy()

        # Always include Cash
        out = pd.concat([out, pd.DataFrame([{"valeur": "Cash", "cours": 1.0}])], ignore_index=True)
        return out

    except Exception:
        return pd.DataFrame()

def _upsert_prices_to_supabase(df: pd.DataFrame) -> None:
    """
    Upsert prices into market_prices (excluding Cash).
    """
    if df is None or df.empty:
        return

    try:
        now = datetime.utcnow().isoformat()
        payload = []
        for _, r in df.iterrows():
            val = str(r.get("valeur", "")).strip()
            if not val or val.lower() == "cash":
                continue
            cours = r.get("cours", 0.0)
            try:
                cours_f = float(cours)
            except Exception:
                cours_f = 0.0
            payload.append({"valeur": val, "cours": cours_f, "updated_at": now})

        if payload:
            prices_table().upsert(payload, on_conflict="valeur").execute()
    except Exception:
        # Silent fail: app should still work even if DB write fails
        pass

@st.cache_data(ttl=60)
def _cached_fetch_stocks() -> pd.DataFrame:
    """
    Main entry:
      1) Try fresh cached prices from Supabase (market_prices)
      2) Else scrape Casablanca Bourse
      3) Save to Supabase (best-effort)
    """
    df_db = _read_prices_from_supabase(max_age_seconds=SUPABASE_PRICES_MAX_AGE_SECONDS)
    if not df_db.empty:
        return df_db

    try:
        df = _scrape_cb_prices()
        _upsert_prices_to_supabase(df)
        return df
    except Exception as e:
        st.error(f"Failed to scrape Casablanca Bourse prices: {e}")
        # Last fallback: try whatever is in Supabase even if stale (better than nothing)
        df_db_any = _read_prices_from_supabase(max_age_seconds=10**9)
        if not df_db_any.empty:
            return df_db_any
        return pd.DataFrame(columns=["valeur", "cours"])

def fetch_stocks() -> pd.DataFrame:
    """Return the live/cached stocks DataFrame with columns [valeur, cours] + Cash row."""
    return _cached_fetch_stocks()

def fetch_instruments():
    """
    Return a DataFrame [instrument_name, nombre_de_titres, facteur_flottant]
    from the 'instruments' Supabase table.
    """
    client = get_supabase()
    res = client.table("instruments").select("*").execute()
    if not res.data:
        return pd.DataFrame(columns=["instrument_name", "nombre_de_titres", "facteur_flottant"])
    df = pd.DataFrame(res.data)
    needed_cols = ["instrument_name", "nombre_de_titres", "facteur_flottant"]
    for col in needed_cols:
        if col not in df.columns:
            df[col] = None
    return df[needed_cols].copy()

##################################################
#           Client / Portfolio / Performance
##################################################

def get_all_clients():
    res = client_table().select("*").execute()
    if not res.data:
        return []
    return [r["name"] for r in res.data]

def get_client_info(client_name: str):
    res = client_table().select("*").eq("name", client_name).execute()
    if res.data:
        return res.data[0]
    return None

def get_client_id(client_name: str):
    cinfo = get_client_info(client_name)
    if not cinfo:
        return None
    return int(cinfo["id"])

def client_has_portfolio(client_name: str) -> bool:
    cid = get_client_id(client_name)
    if cid is None:
        return False
    port = portfolio_table().select("*").eq("client_id", cid).execute()
    return len(port.data) > 0

def get_portfolio(client_name: str) -> pd.DataFrame:
    """Return a DataFrame with portfolio rows for 'client_name'."""
    cid = get_client_id(client_name)
    if cid is None:
        return pd.DataFrame()
    res = portfolio_table().select("*").eq("client_id", cid).execute()
    return pd.DataFrame(res.data)

##################################################
#        CRUD for Clients & Rates
##################################################

def create_client(name: str):
    if not name:
        st.error("Nom du client invalide.")
        return
    try:
        client_table().insert({"name": name}).execute()
        st.success(f"Client '{name}' créé avec succès!")
        st.rerun()
    except Exception as e:
        st.error(f"Erreur lors de la création du client: {e}")

def rename_client(old_name: str, new_name: str):
    cid = get_client_id(old_name)
    if cid is None:
        st.error("Client introuvable.")
        return
    try:
        client_table().update({"name": new_name}).eq("id", cid).execute()
        st.success(f"Client '{old_name}' renommé en '{new_name}'!")
        st.rerun()
    except Exception as e:
        st.error(f"Erreur lors du renommage: {e}")

def delete_client(cname: str):
    cid = get_client_id(cname)
    if cid is None:
        st.error("Client introuvable.")
        return
    try:
        client_table().delete().eq("id", cid).execute()
        st.success(f"Client '{cname}' supprimé.")
        st.rerun()
    except Exception as e:
        st.error(f"Erreur lors de la suppression du client: {e}")

def update_client_rates(client_name: str,
                        exchange_comm: float,
                        is_pea: bool,
                        custom_tax: float,
                        mgmt_fee: float,
                        bill_surperf: bool):
    cid = get_client_id(client_name)
    if cid is None:
        st.error("Client introuvable.")
        return
    try:
        final_tax = 0.0 if is_pea else float(custom_tax)
        client_table().update({
            "exchange_commission_rate": float(exchange_comm),
            "tax_on_gains_rate": final_tax,
            "is_pea": bool(is_pea),
            "management_fee_rate": float(mgmt_fee),
            "bill_surperformance": bool(bill_surperf)
        }).eq("id", cid).execute()
        st.success(f"Paramètres mis à jour pour « {client_name} ».")
        st.rerun()
    except Exception as e:
        st.error(f"Erreur lors de la mise à jour des taux: {e}")

##################################################
#       Performance Periods
##################################################

def create_performance_period(client_id: int, start_date_str: str, start_val: float, masi_start_value: float):
    if not client_id:
        st.error("ID client invalide.")
        return
    try:
        row_data = {
            "client_id": client_id,
            "start_date": start_date_str,
            "start_value": start_val,
            "masi_start_value": masi_start_value
        }
        performance_table().insert(row_data).execute()
    except Exception as e:
        st.error(f"Erreur lors de la création d'une période de performance: {e}")

def get_performance_periods_for_client(client_id: int) -> pd.DataFrame:
    res = performance_table().select("*").eq("client_id", client_id).order("start_date", desc=False).execute()
    if not res.data:
        return pd.DataFrame()
    return pd.DataFrame(res.data)

def get_latest_performance_period_for_all_clients() -> pd.DataFrame:
    res = performance_table().select("*").execute()
    if not res.data:
        return pd.DataFrame()
    df = pd.DataFrame(res.data)
    if df.empty or "start_date" not in df.columns:
        return pd.DataFrame()
    df["start_date"] = pd.to_datetime(df["start_date"], errors="coerce")
    df_sorted = df.sort_values(["client_id", "start_date"], ascending=[True, False])
    df_latest = df_sorted.groupby("client_id", as_index=False).head(1)
    return df_latest

def update_performance_period_rows(old_df: pd.DataFrame, new_df: pd.DataFrame):
    for _, row in new_df.iterrows():
        rec_id = row.get("id", None)
        if rec_id is None:
            continue

        start_dt = row.get("start_date")
        if isinstance(start_dt, date):
            start_dt_str = start_dt.isoformat()
        elif isinstance(start_dt, datetime):
            start_dt_str = start_dt.date().isoformat()
        else:
            start_dt_str = str(start_dt)

        new_start_val = float(row.get("start_value", 0))
        new_masi_val = float(row.get("masi_start_value", 0))

        try:
            performance_table().update({
                "start_date": start_dt_str,
                "start_value": new_start_val,
                "masi_start_value": new_masi_val
            }).eq("id", rec_id).execute()
        except Exception as e:
            st.error(f"Erreur lors de la mise à jour de la ligne id={rec_id}: {e}")

def transactions_table():
    return get_supabase().table("transactions")

def log_transaction(row: dict):
    """Insert one transaction row in Supabase."""
    return transactions_table().insert(row).execute()

def get_transactions(client_id: int | None = None):
    """Return transactions as DataFrame (optionally filtered by client)."""
    q = transactions_table().select("*").order("executed_at", desc=True)
    if client_id is not None:
        q = q.eq("client_id", client_id)
    res = q.execute()
    if not res.data:
        return pd.DataFrame()
    return pd.DataFrame(res.data)
