# db_utils.py
import pandas as pd
import streamlit as st
from db_connection import get_supabase_client

def get_supabase():
    return get_supabase_client()

def fetch_masi_from_cb():
    """
    Fetches the JSON from Casablanca Bourse for 'Principaux indices'
    and returns the current MASI index value as float.
    If not found, returns 0.0 or raises an exception.
    """
    url = "https://www.casablanca-bourse.com/api/proxy/fr/api/bourse/dashboard/grouped_index_watch?"
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        # data is a dict: { "data": [ { "title":"Principaux indices", "items":[... ]}, ... ] }
        # We want to find the item where "index" == "MASI" under "title": "Principaux indices"
        for block in data.get("data", []):
            if block.get("title") == "Principaux indices":
                for item in block.get("items", []):
                    if item.get("index") == "MASI":
                        val_str = item.get("field_index_value", "0")
                        return float(val_str)
        return 0.0
    except Exception as e:
        print("Error fetching MASI index:", e)
        return 0.0

def fetch_stocks():
    """
    Grabs the 'stocks' DataFrame from the IDBourse API.
    This function used to be 'get_stock_list' in your single-file code.
    """
    import streamlit as st
    import requests

    @st.cache_data(ttl=60)
    def _fetch():
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
            st.error(f"Failed to fetch stock data: {e}")
            return pd.DataFrame(columns=["valeur", "cours"])
    return _fetch()

def fetch_instruments():
    """
    Return a DataFrame [instrument_name, nombre_de_titres, facteur_flottant]
    from the 'instruments' table.
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

def client_table():
    return get_supabase().table("clients")

def portfolio_table():
    return get_supabase().table("portfolios")

def get_all_clients():
    """
    Return a list of client names
    """
    res = client_table().select("*").execute()
    if not res.data:
        return []
    return [r["name"] for r in res.data]

def get_client_info(client_name):
    res = client_table().select("*").eq("name", client_name).execute()
    if res.data:
        return res.data[0]
    return None

def get_client_id(client_name):
    cinfo = get_client_info(client_name)
    if not cinfo:
        return None
    return int(cinfo["id"])

def client_has_portfolio(client_name):
    cid = get_client_id(client_name)
    if cid is None:
        return False
    port = portfolio_table().select("*").eq("client_id", cid).execute()
    return len(port.data) > 0

def get_portfolio(client_name):
    cid = get_client_id(client_name)
    if cid is None:
        return pd.DataFrame()
    res = portfolio_table().select("*").eq("client_id", cid).execute()
    return pd.DataFrame(res.data)

# CRUD for clients
def create_client(name):
    import streamlit as st
    if not name:
        st.error("Client name cannot be empty.")
        return
    try:
        client_table().insert({"name": name}).execute()
        st.success(f"Client '{name}' added!")
        st.rerun()
    except Exception as e:
        st.error(f"Error adding client: {e}")

def rename_client(old_name, new_name):
    import streamlit as st
    cid = get_client_id(old_name)
    if cid is None:
        st.error("Client not found.")
        return
    try:
        client_table().update({"name": new_name}).eq("id", cid).execute()
        st.success(f"Renamed '{old_name}' to '{new_name}'")
        st.rerun()
    except Exception as e:
        st.error(f"Error renaming client: {e}")

def delete_client(cname):
    import streamlit as st
    cid = get_client_id(cname)
    if cid is None:
        st.error("Client not found.")
        return
    try:
        client_table().delete().eq("id", cid).execute()
        st.success(f"Deleted client '{cname}'")
        st.rerun()
    except Exception as e:
        st.error(f"Error deleting client: {e}")

def update_client_rates(client_name, exchange_comm, is_pea, custom_tax, mgmt_fee, bill_surperf):
    import streamlit as st
    cid = get_client_id(client_name)
    if cid is None:
        st.error("Client not found to update rates.")
        return
    try:
        final_tax = 0.0 if is_pea else float(custom_tax)
        client_table().update({
            "exchange_commission_rate": float(exchange_comm),
            "tax_on_gains_rate": final_tax,
            "is_pea": is_pea,
            "management_fee_rate": float(mgmt_fee),
            "bill_surperformance": bool(bill_surperf)
        }).eq("id", cid).execute()
        st.success(f"Paramètres mis à jour pour {client_name}")
        st.rerun()
    except Exception as e:
        st.error(f"Erreur lors de la mise à jour: {e}")

def performance_table():
    """
    Returns the Supabase table object for 'performance_periods'.
    """
    return get_supabase_client().table("performance_periods")

def create_performance_period(client_id, start_date_str, start_val):
    """
    Inserts a row into your 'performance_periods' table.
    Make sure the table is created in your DB.
    """
    client = get_supabase()
    try:
        row = {
            "client_id": client_id,
            "start_date": start_date_str,
            "start_value": start_val,
            "masi_start_value": float(masi_start_value)
        }
        client.table("performance_periods").insert(row).execute()
    except Exception as e:
        st.error(f"Erreur lors de la création de la période: {e}")

def get_performance_periods_for_client(client_id):
    res = client.table("performance_periods").select("*").eq("client_id", client_id).order("start_date", desc=False).execute()
    df = pd.DataFrame(res.data) if res.data else pd.DataFrame()
    return df

def get_latest_performance_period_for_all_clients():
    """
    For each client, we want the latest (max) start_date row from performance_periods.
    A naive approach is to fetch all rows, group by client_id, then pick the latest date.
    """
    res = client.table("performance_periods").select("*").execute()
    df = pd.DataFrame(res.data) if res.data else pd.DataFrame()
    if df.empty:
        return pd.DataFrame()
    # group by client_id, pick the row with the max start_date
    df["start_date"] = pd.to_datetime(df["start_date"], errors="coerce")
    # sort descending then group
    df_sorted = df.sort_values(["client_id","start_date"], ascending=[True,False])
    df_latest = df_sorted.groupby("client_id", as_index=False).head(1)
    return df_latest
