# db_utils.py
import pandas as pd
import streamlit as st
import requests
from db_connection import get_supabase_client
from typing import Optional

##################################################
#            Supabase Client & Helpers
##################################################

def get_supabase():
    """Return a global Supabase client from db_connection."""
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

def fetch_masi_from_cb() -> float:
    """
    Fetch MASI index from Casablanca Bourse,
    searching under 'Principaux indices' for 'MASI'.
    Returns 0.0 if not found or on error.
    """
    url = "https://www.casablanca-bourse.com/api/proxy/fr/api/bourse/dashboard/grouped_index_watch?"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        for block in data.get("data", []):
            if block.get("title") == "Principaux indices":
                for item in block.get("items", []):
                    if item.get("index") == "MASI":
                        val_str = item.get("field_index_value", "0")
                        return float(val_str)
        return 0.0
    except Exception as e:
        print("Error fetching MASI from Casablanca Bourse:", e)
        return 0.0

##################################################
#           Fetching Stocks & Instruments
##################################################

@st.cache_data(ttl=60)
def _cached_fetch_stocks() -> pd.DataFrame:
    """
    Actually fetch from IDBourse API, returning DataFrame [valeur, cours],
    with an extra row for 'Cash' at cours=1.
    """
    try:
        r = requests.get("https://backend.idbourse.com/api_2/get_all_data", timeout=10)
        r.raise_for_status()
        data = r.json()
        df = pd.DataFrame(
            [(s.get("name","N/A"), s.get("dernier_cours", 0)) for s in data],
            columns=["valeur","cours"]
        )
        # Add Cash row
        cash = pd.DataFrame([{"valeur":"Cash","cours":1}])
        df = pd.concat([df, cash], ignore_index=True)
        return df
    except Exception as e:
        st.error(f"Failed to fetch stock data from IDBourse: {e}")
        return pd.DataFrame(columns=["valeur","cours"])

def fetch_stocks() -> pd.DataFrame:
    """Return the IDBourse stock list, cached for 60s."""
    return _cached_fetch_stocks()

def fetch_instruments() -> pd.DataFrame:
    """
    Return [instrument_name, nombre_de_titres, facteur_flottant] from 'instruments' table in DB.
    """
    client = get_supabase()
    resp = client.table("instruments").select("*").execute()
    if not resp.data:
        return pd.DataFrame(columns=["instrument_name","nombre_de_titres","facteur_flottant"])
    df = pd.DataFrame(resp.data)
    needed = ["instrument_name","nombre_de_titres","facteur_flottant"]
    for c in needed:
        if c not in df.columns:
            df[c] = None
    return df[needed].copy()

##################################################
#           Client & Portfolio
##################################################

def get_all_clients() -> list[str]:
    """Return the list of all client names."""
    res = client_table().select("*").execute()
    if not res.data:
        return []
    return [r["name"] for r in res.data]

def get_client_info(client_name: str) -> Optional[dict]:
    """
    Return a dict for the client's row or None.
    Example fields: id, name, exchange_commission_rate, ...
    """
    res = client_table().select("*").eq("name", client_name).execute()
    if res.data:
        return res.data[0]
    return None

def get_client_id(client_name: str) -> Optional[int]:
    cinfo = get_client_info(client_name)
    if not cinfo:
        return None
    return int(cinfo["id"])

def client_has_portfolio(client_name: str) -> bool:
    """Check if the client has any row in 'portfolios'."""
    cid = get_client_id(client_name)
    if cid is None:
        return False
    res = portfolio_table().select("*").eq("client_id", cid).execute()
    return len(res.data) > 0

def get_portfolio(client_name: str) -> pd.DataFrame:
    """Return a DataFrame of that client's portfolio rows."""
    cid = get_client_id(client_name)
    if cid is None:
        return pd.DataFrame()
    resp = portfolio_table().select("*").eq("client_id", cid).execute()
    return pd.DataFrame(resp.data)

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
        st.experimental_rerun()
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
        st.experimental_rerun()
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
        st.experimental_rerun()
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
            "bill_surperformance": bool(bill_surperf),
        }).eq("id", cid).execute()

        st.success(f"Paramètres mis à jour pour « {client_name} ».")
        st.experimental_rerun()
    except Exception as e:
        st.error(f"Erreur lors de la mise à jour des taux: {e}")

##################################################
#       Performance Periods
##################################################

def create_performance_period(client_id: int,
                              start_date_str: str,
                              start_val: float,
                              masi_start_value: float):
    """
    Insert a new row in 'performance_periods':
      - client_id
      - start_date => str
      - start_value
      - masi_start_value
    """
    if not client_id:
        st.error("ID client invalide.")
        return
    try:
        data = {
            "client_id": client_id,
            "start_date": start_date_str,
            "start_value": start_val,
            "masi_start_value": masi_start_value
        }
        performance_table().insert(data).execute()
    except Exception as e:
        st.error(f"Erreur lors de la création d'une période de performance: {e}")

def get_performance_periods_for_client(client_id: int) -> pd.DataFrame:
    """All rows from performance_periods for this client, ascending by date."""
    resp = performance_table().select("*").eq("client_id", client_id).order("start_date", desc=False).execute()
    if not resp.data:
        return pd.DataFrame()
    return pd.DataFrame(resp.data)

def get_latest_performance_period_for_all_clients() -> pd.DataFrame:
    """
    For each client_id, pick row with the greatest start_date.
    Return columns [id, client_id, start_date, start_value, masi_start_value, ...].
    """
    resp = performance_table().select("*").execute()
    if not resp.data:
        return pd.DataFrame()
    df = pd.DataFrame(resp.data)
    if df.empty or "start_date" not in df.columns:
        return pd.DataFrame()

    df["start_date"] = pd.to_datetime(df["start_date"], errors="coerce")
    df.sort_values(["client_id","start_date"], ascending=[True, False], inplace=True)
    # group => pick top row
    latest = df.groupby("client_id", as_index=False).head(1)
    return latest

def update_performance_period_rows(old_df: pd.DataFrame, new_df: pd.DataFrame):
    """
    Compare old_df vs new_df row by row. 
    Here we assume each row has a unique primary key, e.g. "id". 
    Then we detect changes in start_date / start_value / masi_start_value, etc.

    We'll do a simple approach:
      - Match on "id"
      - If changed => update in DB
    """
    if "id" not in old_df.columns:
        st.warning("No 'id' column for performance_periods, can't update reliably.")
        return

    # Convert date columns back to str if needed
    # In your DB, you might store it as text or date.
    # We'll store as 'YYYY-MM-DD' text.
    new_df = new_df.copy()
    if "start_date" in new_df.columns:
        new_df["start_date"] = new_df["start_date"].astype(str)

    for index, new_row in new_df.iterrows():
        row_id = new_row.get("id", None)
        if pd.isna(row_id):
            continue
        # find old row
        old_match = old_df[old_df["id"]==row_id]
        if old_match.empty:
            continue

        old_row = old_match.iloc[0]
        changed = False

        fields_to_check = ["start_date","start_value","masi_start_value"]
        updated_data = {}
        for f in fields_to_check:
            old_val = old_row.get(f, None)
            new_val = new_row.get(f, None)
            # convert to float or str
            if f=="start_date":
                if str(old_val)!=str(new_val):
                    updated_data[f] = str(new_val)
                    changed = True
            else:
                # numeric
                try:
                    old_v = float(old_val)
                    new_v = float(new_val)
                    if not math.isclose(old_v, new_v, rel_tol=1e-9, abs_tol=1e-9):
                        updated_data[f] = new_v
                        changed = True
                except:
                    pass

        if changed:
            try:
                performance_table().update(updated_data).eq("id", row_id).execute()
            except Exception as e:
                st.error(f"Erreur lors de la mise à jour de la période (id={row_id}): {e}")
