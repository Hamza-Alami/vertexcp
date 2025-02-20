# db_utils.py
import pandas as pd
import streamlit as st
from db_connection import get_supabase_client

def get_supabase():
    return get_supabase_client()

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

def update_client_rates(client_name, exchange_comm, is_pea, custom_tax, mgmt_fee):
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
            "management_fee_rate": float(mgmt_fee)
        }).eq("id", cid).execute()
        st.success(f"Updated rates for {client_name}")
        st.rerun()
    except Exception as e:
        st.error(f"Error updating client rates: {e}")

def performance_table():
    """
    Returns the Supabase table object for 'performance_periods'.
    """
    return get_supabase_client().table("performance_periods")

def create_performance_period(client_id: int, start_date: str, start_value: float):
    """
    Inserts a new performance period row for (client_id, start_date, start_value).
    start_date in 'YYYY-MM-DD' format or any date recognized by Postgres.
    """
    try:
        res = performance_table().insert({
            "client_id": client_id,
            "start_date": start_date,   # e.g. '2025-02-28'
            "start_value": start_value
        }).execute()
        if res.data:
            st.success("Performance period created!")
        else:
            st.error(f"Failed to create performance period: {res.error}")
    except Exception as e:
        st.error(f"DB Error creating performance period: {e}")

def get_performance_periods_for_client(client_id: int):
    """
    Returns all performance_periods rows for the given client_id, sorted by date DESC.
    """
    res = performance_table().select("*").eq("client_id", client_id).order("start_date", desc=True).execute()
    if res.data:
        return pd.DataFrame(res.data)
    return pd.DataFrame(columns=["id","client_id","start_date","start_value","created_at"])

def get_latest_performance_period_for_all_clients():
    """
    For each client that has at least one performance_period entry,
    fetch the *most recent* row (by start_date) and return them in a DataFrame.
    We can do this by grouping or by a 2-step approach in Python.
    """
    # Grab all rows
    all_res = performance_table().select("*").execute()
    if not all_res.data:
        return pd.DataFrame(columns=["client_id","start_date","start_value"])
    
    df = pd.DataFrame(all_res.data)
    if df.empty:
        return df
    
    # Sort by (client_id, start_date DESC) so the first row per client is the newest
    df = df.sort_values(["client_id","start_date"], ascending=[True,False])
    # group by client_id, take first row => "most recent" per client
    latest = df.groupby("client_id", as_index=False).head(1)
    return latest.reset_index(drop=True)
