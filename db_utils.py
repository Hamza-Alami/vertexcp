import json
import re
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
    Uses browser-like headers and retries with/without SSL verification.
    """

    url = "https://www.casablanca-bourse.com/api/proxy/fr/api/bourse/dashboard/grouped_index_watch?"

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
        "Referer": "https://www.casablanca-bourse.com/",
        "Connection": "keep-alive",
    }

    session = requests.Session()

    for verify_mode in (certifi.where(), False):

        try:
            response = session.get(
                url,
                headers=headers,
                timeout=20,
                verify=verify_mode,
            )

            response.raise_for_status()

            data = response.json()

            for block in data.get("data", []):

                title = (block.get("title") or "").strip().lower()

                if "principaux" in title and "indice" in title:

                    for item in block.get("items", []):

                        if (
                            (item.get("index") or "")
                            .strip()
                            .upper()
                            == "MASI"
                        ):

                            val_str = str(
                                item.get("field_index_value", "0")
                            )

                            val_str = (
                                val_str
                                .replace(" ", "")
                                .replace(",", ".")
                            )

                            try:
                                return float(val_str)

                            except ValueError:
                                return 0.0

            return 0.0

        except requests.exceptions.SSLError:
            continue

        except Exception as e:

            if verify_mode is False:
                st.warning(f"⚠️ MASI API unavailable: {e}")
                return 0.0

    return 0.0

##################################################
#     Casablanca Bourse — Live market (Actions)
##################################################

CB_LIVE_ACTIONS_URL = "https://www.casablanca-bourse.com/live-market/actions"

_CB_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Referer": "https://www.casablanca-bourse.com/",
}

# Freshness logic:
# - Streamlit cache: 60s
# - Supabase cached prices considered fresh for: 180s
SUPABASE_PRICES_MAX_AGE_SECONDS = 180

# Portfolios / instruments use BMCE-style short names (e.g. "Addoha"), not tickers ("ADH").
# Map Casablanca Bourse symbols back to those labels for merge compatibility.
_BMCE_NAME_BY_SYMBOL = {
    "ADH": "Addoha",
    "ADI": "Alliances",
    "AFI": "Afric Indus.",
    "AFM": "AFMA",
    "AKT": "Akdital",
    "ALM": "Aluminium Maroc",
    "ARD": "Aradei Capital",
    "ATH": "Auto Hall",
    "ATL": "ATLANTASANAD",
    "ATW": "Attijariwafa Bank",
    "BCI": "BMCI",
    "BCP": "BCP",
    "BOA": "BoA",
    "CAP": "Cash Plus",
    "CDM": "CDM",
    "CFG": "CFG Bank",
    "CIH": "CIH",
    "CMA": "Ciments Maroc",
    "CMG": "CMGP GROUP",
    "COL": "Colorado",
    "CRS": "Cartier Saada",
    "CSR": "COSUMAR",
    "CTM": "CTM",
    "DHO": "Delta Holding",
    "DRI": "Dari Couspate",
    "DWY": "DISWAY",
    "DYT": "Disty Technolog",
    "FBR": "FENIE BROSSETTE",
    "GAZ": "Afriquia Gaz",
    "GTM": "SGTM",
    "HPS": "HPS",
    "IAM": "Maroc Telecom",
    "IBC": "IBMaroc.com",
    "IMO": "Immorente",
    "INV": "INVOLYS",
    "JET": "Jet Contractors",
    "LBV": "LABEL VIE",
    "LES": "Lesieur Cristal",
    "LHM": "Holcim Maroc",
    "M2M": "M2M Group",
    "MAB": "Maghrebail",
    "MDP": "Med Paper",
    "MIC": "Microdata",
    "MLE": "Maroc Leasing",
    "MNG": "Managem",
    "MOX": "Maghreb Oxygene",
    "MSA": "Marsa Maroc",
    "MUT": "Mutandis",
    "NKL": "Ennakl",
    "OUL": "Oulmes",
    "RDS": "Resid Dar Saada",
    "REB": "Rebab Company",
    "RIS": "Risma",
    "S2M": "S2M",
    "SAH": "Sanlam Maroc",
    "SBM": "Ste Boissons",
    "SID": "Sonasid",
    "SLF": "SALAFIN",
    "SMI": "SMI",
    "SNA": "SNA",
    "SNP": "SNEP",
    "SOT": "SOTHEMA",
    "SRM": "SRM",
    "STR": "STROC Indus.",
    "T2S": "T2S Gro Holding",
    "TGC": "TGCC",
    "TMA": "TotalEnergie MM",
    "TQM": "TAQA Morocco",
    "VCN": "Vicenne",
    "WAA": "Wafa Assur",
    "ZDJ": "Zellidja",
}
_SYMBOL_BY_BMCE_NAME = {v: k for k, v in _BMCE_NAME_BY_SYMBOL.items()}


def _normalize_valeur_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).strip().lower())


def _portfolio_valeur_for_symbol(symbol: str, emetteur_fr: str = "") -> str:
    """Return the portfolio-facing label for a Casablanca Bourse ticker."""
    sym = (symbol or "").strip().upper()
    if sym in _BMCE_NAME_BY_SYMBOL:
        return _BMCE_NAME_BY_SYMBOL[sym]
    if emetteur_fr:
        return emetteur_fr.strip()
    return sym


def lookup_stock_price(valeur: str, stocks_df: pd.DataFrame) -> float:
    """
    Resolve a live price for a portfolio/instrument label.
    Handles BMCE short names, tickers, and case differences.
    """
    if valeur is None:
        return 0.0
    val = str(valeur).strip()
    if not val or val.lower() == "cash":
        return 1.0
    if stocks_df is None or stocks_df.empty:
        return 0.0

    candidates = {val, val.lower(), val.upper()}
    sym = _SYMBOL_BY_BMCE_NAME.get(val)
    if sym:
        candidates.add(sym)
        candidates.add(sym.lower())

    for key in candidates:
        match = stocks_df[stocks_df["valeur"] == key]
        if not match.empty:
            return float(match["cours"].iloc[0])

    if "symbol" in stocks_df.columns:
        for key in candidates:
            match = stocks_df[stocks_df["symbol"].str.upper() == str(key).upper()]
            if not match.empty:
                return float(match["cours"].iloc[0])

    target = _normalize_valeur_key(val)
    for _, row in stocks_df.iterrows():
        for col in ("valeur", "symbol", "name"):
            if col not in stocks_df.columns:
                continue
            cell = row.get(col)
            if cell is None:
                continue
            if _normalize_valeur_key(cell) == target:
                return float(row["cours"])
    return 0.0


def _supabase_cache_looks_like_tickers(df: pd.DataFrame) -> bool:
    """Detect stale cache rows keyed by tickers instead of portfolio labels."""
    if df is None or df.empty or "valeur" not in df.columns:
        return False
    non_cash = df[df["valeur"].astype(str).str.lower() != "cash"]["valeur"].astype(str)
    if non_cash.empty:
        return False
    ticker_like = non_cash.str.fullmatch(r"[A-Z0-9]{2,5}")
    return ticker_like.mean() >= 0.8

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

def _fetch_cb_live_actions_html() -> str:
    """Fetch Casablanca Bourse live actions page (browser headers, SSL fallback)."""
    last_err: Optional[Exception] = None
    for verify_mode in (certifi.where(), False):
        try:
            r = requests.get(
                CB_LIVE_ACTIONS_URL,
                timeout=20,
                headers=_CB_BROWSER_HEADERS,
                verify=verify_mode,
            )
            r.raise_for_status()
            return r.text
        except Exception as e:
            last_err = e
            if verify_mode is False:
                raise
    raise last_err or RuntimeError("Unknown scraping error")

def _parse_actions_from_drupal_json(html: str) -> list:
    """Parse instrument tickers and Dernier prices from embedded Drupal settings."""
    match = re.search(
        r'<script type="application/json" data-drupal-selector="drupal-settings-json">(.*?)</script>',
        html,
        re.S,
    )
    if not match:
        return []

    data = json.loads(match.group(1))
    actions = data.get("live_market", {}).get("actions", [])
    rows = []
    for action in actions:
        symbol = (action.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        try:
            cours = float(action.get("dernierCours") or 0)
        except (TypeError, ValueError):
            cours = 0.0
        emetteur_fr = (action.get("emetteur") or {}).get("fr") or ""
        rows.append({
            "symbol": symbol,
            "name": emetteur_fr.strip(),
            "valeur": _portfolio_valeur_for_symbol(symbol, emetteur_fr),
            "cours": cours,
        })
    return rows

def _parse_actions_from_html(soup: BeautifulSoup) -> list:
    """Fallback: parse #desktop-table or #mobile-cards when JSON is unavailable."""
    rows = []

    tbody = soup.find("tbody", id="table-body")
    if tbody:
        for tr in tbody.find_all("tr"):
            link = tr.find("a", class_="hover-underline")
            if not link:
                continue
            symbol = link.get_text(strip=True).upper()
            if not symbol:
                continue
            tds = tr.find_all("td")
            # Columns: fav, expand, instrument, statut, sell qty/px, buy px/qty, Dernier, ...
            price = _parse_float_fr(tds[8].get_text(" ", strip=True)) if len(tds) >= 9 else 0.0
            rows.append({
                "symbol": symbol,
                "name": "",
                "valeur": _portfolio_valeur_for_symbol(symbol),
                "cours": price,
            })
        if rows:
            return rows

    mobile_cards = soup.find("div", id="mobile-cards")
    if mobile_cards:
        for header in mobile_cards.select(".mobile-card-header[data-ticker]"):
            symbol = (header.get("data-ticker") or "").strip().upper()
            if not symbol:
                continue
            price = 0.0
            for block in header.find_all("div", style=re.compile(r"text-align:\s*right")):
                parts = block.find_all("div", recursive=False)
                if len(parts) >= 2 and parts[0].get_text(strip=True) == "Dernier":
                    price = _parse_float_fr(parts[1].get_text(" ", strip=True))
                    break
            rows.append({
                "symbol": symbol,
                "name": "",
                "valeur": _portfolio_valeur_for_symbol(symbol),
                "cours": price,
            })

    return rows

def _scrape_cb_prices() -> pd.DataFrame:
    """
    Scrape Casablanca Bourse live market (Actions) and return DataFrame [valeur, cours].
    Uses embedded Drupal JSON (Instrument = ticker, Dernier = dernierCours); falls back
    to #desktop-table / #mobile-cards HTML. Always appends Cash (cours=1.0).
    """
    html = _fetch_cb_live_actions_html()
    rows = _parse_actions_from_drupal_json(html)

    if not rows:
        soup = BeautifulSoup(html, "lxml")
        rows = _parse_actions_from_html(soup)

    if not rows:
        raise RuntimeError(
            "Casablanca Bourse live market data not found (Drupal JSON and HTML table missing)"
        )

    df = pd.DataFrame(rows).drop_duplicates(subset=["valeur"], keep="last")
    if df.empty:
        df = pd.DataFrame(columns=["valeur", "cours"])

    cash_row = {"symbol": "CASH", "name": "Cash", "valeur": "Cash", "cours": 1.0}
    df = pd.concat([df, pd.DataFrame([cash_row])], ignore_index=True)
    cols = [c for c in ("symbol", "name", "valeur", "cours") if c in df.columns]
    return df[cols]

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
      2) Else scrape Casablanca Bourse live market (Actions)
      3) Save to Supabase (best-effort)
    """
    df_db = _read_prices_from_supabase(max_age_seconds=SUPABASE_PRICES_MAX_AGE_SECONDS)
    if not df_db.empty and not _supabase_cache_looks_like_tickers(df_db):
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
