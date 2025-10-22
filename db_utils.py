import pandas as pd
import streamlit as st
import requests
from db_connection import get_supabase_client
from datetime import date, datetime

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

##################################################
#               MASI Fetch
##################################################
import certifi
import urllib3
import requests

# Disable warnings if we need to fall back to verify=False
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def fetch_masi_from_cb():
    """
    Fetch MASI index from Casablanca Bourse API.
    Tries with SSL verification first; if it fails, retries without verification.
    """
    url = "https://www.casablanca-bourse.com/api/proxy/fr/api/bourse/dashboard/grouped_index_watch?"
    
    for verify_mode in (certifi.where(), False):  # try secure first, then fallback
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
                            return float(val_str)
            return 0.0

        except Exception as e:
            if verify_mode is False:
                # Final failure after fallback
                st.error(f"❌ Still cannot fetch MASI index: {e}")
                return 0.0
            # Retry without verification
            continue


##################################################
#       Fetching Stocks & Instruments
##################################################

@st.cache_data(ttl=60)
def _cached_fetch_stocks():
    """
    Actually fetch from IDBourse API, returning a DataFrame with columns: [valeur, cours].
    Adds a 'Cash' row with cours=1.
    """
    try:
        response = requests.get("https://backend.idbourse.com/api_2/get_all_data", timeout=10)
        response.raise_for_status()
        data = response.json()
        df = pd.DataFrame(
            [(s.get("name", "N/A"), s.get("dernier_cours", 0)) for s in data],
            columns=["valeur", "cours"]
        )
        # Add CASH row
        cash_row = pd.DataFrame([{"valeur": "Cash", "cours": 1}])
        return pd.concat([df, cash_row], ignore_index=True)
    except Exception as e:
        st.error(f"Failed to fetch stock data from IDBourse: {e}")
        return pd.DataFrame(columns=["valeur", "cours"])

def fetch_stocks():
    """
    Return the 'stocks' DataFrame from the IDBourse API, cached for 60s.
    Override: Replace 'ARADEI CAPITAL' with 'VICENNE' and force cours=440.
    """
    df = _cached_fetch_stocks().copy()

    override_real_name = "ARADEI CAPITAL"
    custom_name = "VICENNE"
    custom_price = 500.1

    mask = df["valeur"] == override_real_name
    if mask.any():
        df.loc[mask, "valeur"] = custom_name
        df.loc[mask, "cours"] = custom_price
    else:
        # In case ARADEI CAPITAL is missing from API, just add VICENNE
        new_row = pd.DataFrame([{"valeur": custom_name, "cours": custom_price}])
        df = pd.concat([df, new_row], ignore_index=True)

    return df

def fetch_instruments():
    """
    Return a DataFrame [instrument_name, nombre_de_titres, facteur_flottant]
    from the 'instruments' Supabase table.
    """
    client = get_supabase()
    res = client.table("instruments").select("*").execute()
    if not res.data:
        return pd.DataFrame(columns=["instrument_name","nombre_de_titres","facteur_flottant"])
    df = pd.DataFrame(res.data)
    needed_cols = ["instrument_name","nombre_de_titres","facteur_flottant"]
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
    """Return a DataFrame with portfolio rows for 'client_name'. Normalize ARADEI → VICENNE."""
    cid = get_client_id(client_name)
    if cid is None:
        return pd.DataFrame()
    res = portfolio_table().select("*").eq("client_id", cid).execute()
    df = pd.DataFrame(res.data)

    if not df.empty and "valeur" in df.columns:
        df["valeur"] = df["valeur"].replace("ARADEI CAPITAL", "VICENNE")

    return df

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
    for idx, row in new_df.iterrows():
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
