import os
import json
from datetime import date
from typing import Optional

import pandas as pd
import streamlit as st
import requests

from db_connection import get_supabase_client


##################################################
#            Supabase Client & Helpers
##################################################

def get_supabase():
    """Return Supabase client from db_connection.py"""
    return get_supabase_client()


def _to_df(data):
    if not data:
        return pd.DataFrame()
    return pd.DataFrame(data)


##################################################
#            Table Shortcuts
##################################################

def client_table():
    return get_supabase().table("clients")

def portfolio_table():
    return get_supabase().table("portfolios")

def performance_table():
    return get_supabase().table("performance_periods")

def instruments_table():
    return get_supabase().table("instruments")

def market_prices_table():
    return get_supabase().table("market_prices")

def strategies_table():
    return get_supabase().table("strategies")

def transactions_table():
    return get_supabase().table("transactions")


##################################################
#            MASI Fetch (Robuste)
##################################################
def fetch_masi_from_cb() -> float:
    """
    Fetch MASI from an endpoint if configured.
    - If you already have a new MASI API (Vicente), set:
        st.secrets["MASI_ENDPOINT"] or env var MASI_ENDPOINT
    - The endpoint can return:
        - {"masi": 12345.6} or {"value": 12345.6} or {"last": 12345.6}
        - or nested field; we try common keys.
    If no endpoint => returns 0.0 (no crash).
    """
    endpoint = None
    try:
        endpoint = st.secrets.get("MASI_ENDPOINT")
    except Exception:
        endpoint = None

    endpoint = endpoint or os.getenv("MASI_ENDPOINT")
    if not endpoint:
        return 0.0

    r = requests.get(endpoint, timeout=10)
    r.raise_for_status()
    js = r.json()

    # Try common keys
    for k in ["masi", "value", "last", "dernier", "dernier_cours", "close"]:
        if isinstance(js, dict) and k in js:
            try:
                return float(js[k])
            except Exception:
                pass

    # try nested
    if isinstance(js, dict):
        # e.g. {"data":{"masi":...}}
        for subk in ["data", "result", "payload"]:
            if subk in js and isinstance(js[subk], dict):
                for k in ["masi", "value", "last", "close"]:
                    if k in js[subk]:
                        try:
                            return float(js[subk][k])
                        except Exception:
                            pass

    return 0.0


##################################################
#            Clients CRUD
##################################################

def get_all_clients():
    res = client_table().select("name").order("name").execute()
    if not res.data:
        return []
    return [r["name"] for r in res.data if "name" in r]


def get_client_id(client_name: str) -> Optional[int]:
    if not client_name:
        return None
    res = client_table().select("id").eq("name", client_name).limit(1).execute()
    if not res.data:
        return None
    return int(res.data[0]["id"])


def get_client_info(client_name: str) -> dict:
    cid = get_client_id(client_name)
    if cid is None:
        return {}
    res = client_table().select("*").eq("id", cid).limit(1).execute()
    if not res.data:
        return {}
    return res.data[0]


def create_client(client_name: str):
    if not client_name or not client_name.strip():
        st.error("Nom du client invalide.")
        return
    try:
        client_table().insert({
            "name": client_name.strip(),
            "exchange_commission_rate": 0.0,
            "tax_on_gains_rate": 15.0,
            "is_pea": False,
            "management_fee_rate": 0.0,
            "bill_surperformance": False,
            "strategy_id": None
        }).execute()
        st.success(f"Client '{client_name}' créé.")
    except Exception as e:
        st.error(f"Erreur création client: {e}")


def rename_client(old_name: str, new_name: str):
    if not old_name or not new_name:
        st.error("Nom invalide.")
        return
    cid = get_client_id(old_name)
    if cid is None:
        st.error("Client introuvable.")
        return
    try:
        client_table().update({"name": new_name.strip()}).eq("id", cid).execute()
        st.success(f"Client renommé: {old_name} → {new_name}")
    except Exception as e:
        st.error(f"Erreur renommage: {e}")


def delete_client(client_name: str):
    cid = get_client_id(client_name)
    if cid is None:
        st.error("Client introuvable.")
        return
    try:
        client_table().delete().eq("id", cid).execute()
        st.success(f"Client '{client_name}' supprimé.")
    except Exception as e:
        st.error(f"Erreur suppression client: {e}")


def update_client_rates(client_name: str, exchange_commission_rate: float, is_pea: bool,
                        tax_on_gains_rate: float, management_fee_rate: float, bill_surperformance: bool):
    cid = get_client_id(client_name)
    if cid is None:
        st.error("Client introuvable.")
        return
    try:
        client_table().update({
            "exchange_commission_rate": float(exchange_commission_rate),
            "is_pea": bool(is_pea),
            "tax_on_gains_rate": float(tax_on_gains_rate),
            "management_fee_rate": float(management_fee_rate),
            "bill_surperformance": bool(bill_surperformance),
        }).eq("id", cid).execute()
        st.success("Paramètres client mis à jour.")
    except Exception as e:
        st.error(f"Erreur update paramètres: {e}")


##################################################
#            Portfolios
##################################################

def client_has_portfolio(client_name: str) -> bool:
    cid = get_client_id(client_name)
    if cid is None:
        return False
    res = portfolio_table().select("id").eq("client_id", cid).limit(1).execute()
    return bool(res.data)


def get_portfolio(client_name: str) -> pd.DataFrame:
    cid = get_client_id(client_name)
    if cid is None:
        return pd.DataFrame()
    res = portfolio_table().select("*").eq("client_id", cid).execute()
    df = _to_df(res.data)
    if df.empty:
        return df
    return df


##################################################
#            Market Data
##################################################

@st.cache_data(ttl=60)
def fetch_stocks() -> pd.DataFrame:
    """
    Returns a DataFrame with columns: valeur, cours
    from public.market_prices.
    """
    res = market_prices_table().select("valeur,cours,updated_at").execute()
    df = _to_df(res.data)

    if df.empty:
        return pd.DataFrame(columns=["valeur", "cours"])

    # normalize
    df["valeur"] = df["valeur"].astype(str)
    df["cours"] = pd.to_numeric(df["cours"], errors="coerce").fillna(0.0).astype(float)

    # Ensure Cash exists (optional in price table)
    if not (df["valeur"].str.lower() == "cash").any():
        df = pd.concat([df, pd.DataFrame([{"valeur": "Cash", "cours": 1.0}])], ignore_index=True)

    return df[["valeur", "cours"]]


@st.cache_data(ttl=300)
def fetch_instruments() -> pd.DataFrame:
    res = instruments_table().select("*").execute()
    df = _to_df(res.data)
    if df.empty:
        return df
    # normalize
    if "instrument_name" in df.columns:
        df["instrument_name"] = df["instrument_name"].astype(str)
    for c in ["nombre_de_titres", "facteur_flottant"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    return df


##################################################
#            Performance Periods
##################################################

def create_performance_period(client_id: int, start_date: str, start_value: float, masi_start_value: float):
    try:
        performance_table().insert({
            "client_id": int(client_id),
            "start_date": str(start_date),
            "start_value": float(start_value),
            "masi_start_value": float(masi_start_value),
        }).execute()
        st.success("Période de performance créée.")
    except Exception as e:
        st.error(f"Erreur création période: {e}")


def get_performance_periods_for_client(client_id: int) -> pd.DataFrame:
    res = performance_table().select("*").eq("client_id", int(client_id)).order("start_date", desc=True).execute()
    return _to_df(res.data)


def get_latest_performance_period_for_all_clients() -> pd.DataFrame:
    """
    Returns the latest performance period per client by start_date.
    Done in Python (simple & reliable).
    """
    res = performance_table().select("*").execute()
    df = _to_df(res.data)
    if df.empty:
        return df
    df["start_date"] = pd.to_datetime(df["start_date"], errors="coerce")
    df = df.sort_values(["client_id", "start_date"], ascending=[True, False])
    df_latest = df.groupby("client_id", as_index=False).head(1).reset_index(drop=True)
    # Keep start_date as string (Streamlit friendly)
    df_latest["start_date"] = df_latest["start_date"].dt.date.astype(str)
    return df_latest


##################################################
#            Transactions (TPCVM log)
##################################################

def log_transaction(row: dict):
    """Insert one transaction row in Supabase."""
    return transactions_table().insert(row).execute()


def get_transactions(client_id: Optional[int] = None) -> pd.DataFrame:
    q = transactions_table().select("*").order("executed_at", desc=True)
    if client_id is not None:
        q = q.eq("client_id", int(client_id))
    res = q.execute()
    return _to_df(res.data)
