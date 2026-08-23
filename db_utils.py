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
#     Casablanca Bourse — Live market pages
##################################################

CB_LIVE_ACTIONS_URL = "https://www.casablanca-bourse.com/live-market/actions"
CB_LIVE_INDICES_URL = "https://www.casablanca-bourse.com/live-market/indices"

_CB_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Referer": "https://www.casablanca-bourse.com/",
}

# Disable warnings if we need to fall back to verify=False
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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
    "CMT": "MINIERE TOUISSIT",
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
    "RDS": "RESIDENCES DAR SAADA",
    "REB": "Rebab Company",
    "RIS": "RISMA",
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

# Older portfolio DB rows may use labels that differ from BMCE short names.
_LEGACY_PORTFOLIO_ALIASES = {
    "Resid Dar Saada": "RESIDENCES DAR SAADA",
    "Resid Dar saada": "RESIDENCES DAR SAADA",
    "resid dar saada": "RESIDENCES DAR SAADA",
}


def _legacy_portfolio_label(valeur: str) -> str:
    """Map known legacy portfolio labels to the canonical scraper label."""
    val = str(valeur).strip()
    if not val:
        return val
    if val in _LEGACY_PORTFOLIO_ALIASES:
        return _LEGACY_PORTFOLIO_ALIASES[val]
    lower = val.lower()
    for old, new in _LEGACY_PORTFOLIO_ALIASES.items():
        if old.lower() == lower:
            return new
    return val


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


def canonical_valeur(valeur: str) -> str:
    """Normalize portfolio/strategy labels (ticker or short name) to one canonical name."""
    if valeur is None:
        return ""
    val = str(valeur).strip()
    if not val:
        return ""
    if val.lower() == "cash":
        return "Cash"
    sym = val.upper()
    if sym in _BMCE_NAME_BY_SYMBOL:
        return _BMCE_NAME_BY_SYMBOL[sym]
    if val in _SYMBOL_BY_BMCE_NAME:
        return val
    return _legacy_portfolio_label(val)


def _enrich_stocks_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure symbol/name/variation/volume columns exist so lookups & market UI work."""
    if df is None or df.empty:
        return df
    out = df.copy()
    if "symbol" not in out.columns:
        out["symbol"] = out["valeur"].apply(
            lambda v: _SYMBOL_BY_BMCE_NAME.get(str(v).strip(), "")
        )
    if "name" not in out.columns:
        out["name"] = ""
    if "variation" not in out.columns:
        out["variation"] = 0.0
    if "volume" not in out.columns:
        out["volume"] = 0.0
    out["variation"] = out["variation"].apply(lambda x: _safe_float(x))
    out["volume"] = out["volume"].apply(lambda x: _safe_float(x))
    return out


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

    canonical = canonical_valeur(val)
    candidates = {val, val.lower(), val.upper(), canonical, _legacy_portfolio_label(val)}
    sym = _SYMBOL_BY_BMCE_NAME.get(val) or _SYMBOL_BY_BMCE_NAME.get(canonical)
    if sym:
        candidates.add(sym)
        candidates.add(sym.lower())
    sym_upper = val.upper()
    if sym_upper in _BMCE_NAME_BY_SYMBOL:
        candidates.add(_BMCE_NAME_BY_SYMBOL[sym_upper])

    stocks_df = _enrich_stocks_dataframe(stocks_df)

    for key in candidates:
        if not key:
            continue
        match = stocks_df[stocks_df["valeur"] == key]
        if not match.empty:
            return float(match["cours"].iloc[0])

    if "symbol" in stocks_df.columns:
        for key in candidates:
            if not key:
                continue
            match = stocks_df[stocks_df["symbol"].str.upper() == str(key).upper()]
            if not match.empty:
                return float(match["cours"].iloc[0])

    target = _normalize_valeur_key(val)
    canon_target = _normalize_valeur_key(canonical)
    for _, row in stocks_df.iterrows():
        for col in ("valeur", "symbol", "name"):
            if col not in stocks_df.columns:
                continue
            cell = row.get(col)
            if cell is None:
                continue
            cell_norm = _normalize_valeur_key(cell)
            if cell_norm in (target, canon_target):
                return float(row["cours"])
            if target and len(target) >= 4 and (target in cell_norm or cell_norm in target):
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

def _fetch_cb_page(url: str) -> str:
    """Fetch a Casablanca Bourse live-market page (browser headers, SSL fallback)."""
    last_err: Optional[Exception] = None
    for verify_mode in (certifi.where(), False):
        try:
            r = requests.get(
                url,
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


def _fetch_cb_live_actions_html() -> str:
    return _fetch_cb_page(CB_LIVE_ACTIONS_URL)


def _parse_drupal_settings_json(html: str) -> dict:
    match = re.search(
        r'<script type="application/json" data-drupal-selector="drupal-settings-json">(.*?)</script>',
        html,
        re.S,
    )
    if not match:
        return {}
    return json.loads(match.group(1))


def _empty_masi_details() -> dict:
    return {
        "value": 0.0,
        "change_pct": 0.0,
        "change_ytd": 0.0,
        "volume": 0.0,
    }


def _safe_float(x, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        return float(x)
    except (TypeError, ValueError):
        return default


def _parse_masi_details_from_drupal_json(html: str) -> dict:
    """Parse MASI value / variation / YTD from embedded live_market.indices JSON."""
    data = _parse_drupal_settings_json(html)
    indices = data.get("live_market", {}).get("indices", {})
    buckets = []
    if isinstance(indices, dict):
        buckets = [indices.get("principaux", []), indices.get("all", [])]
    elif isinstance(indices, list):
        buckets = [indices]

    for items in buckets:
        if not isinstance(items, list):
            continue
        for item in items:
            code = (item.get("code") or item.get("symbol") or "").strip().upper()
            label_fr = ((item.get("label") or {}).get("fr") or "").strip().upper()
            if code == "MASI" or label_fr == "MASI":
                return {
                    "value": _safe_float(item.get("value")),
                    "change_pct": _safe_float(item.get("change_pct")),
                    "change_ytd": _safe_float(item.get("change_ytd")),
                    "volume": _safe_float(item.get("volume")),
                }
    return _empty_masi_details()


def _parse_masi_details_from_html(soup: BeautifulSoup) -> dict:
    """Fallback: parse MASI card / table (value, variation %, YTD)."""
    out = _empty_masi_details()

    for card in soup.select(".index-card"):
        name_el = card.select_one(".index-card-name")
        if not name_el or name_el.get_text(strip=True).upper() != "MASI":
            continue
        val_el = card.select_one(".index-card-value")
        if val_el:
            out["value"] = _parse_float_fr(val_el.get_text(" ", strip=True))
        badge = card.select_one(".change-badge")
        if badge:
            out["change_pct"] = _parse_float_fr(
                badge.get_text(" ", strip=True).replace("%", "").replace("▲", "").replace("▼", "")
            )
        ytd = card.select_one(".index-card-ytd-val")
        if ytd:
            out["change_ytd"] = _parse_float_fr(ytd.get_text(" ", strip=True).replace("%", ""))
        return out

    tbody = soup.find("tbody", id="table-body")
    if tbody:
        for tr in tbody.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) >= 2 and tds[0].get_text(strip=True).upper() == "MASI":
                out["value"] = _parse_float_fr(tds[1].get_text(" ", strip=True))
                if len(tds) >= 3:
                    out["change_pct"] = _parse_float_fr(
                        tds[2].get_text(" ", strip=True).replace("%", "").replace("▲", "").replace("▼", "")
                    )
                if len(tds) >= 4:
                    out["change_ytd"] = _parse_float_fr(
                        tds[3].get_text(" ", strip=True).replace("%", "")
                    )
                return out
    return out


def _market_volume_from_actions() -> float:
    """Sum traded volumes from the live actions page (MAD)."""
    try:
        html = _fetch_cb_live_actions_html()
        data = _parse_drupal_settings_json(html)
        actions = data.get("live_market", {}).get("actions", [])
        total = 0.0
        for action in actions:
            total += _safe_float(action.get("volume"))
        return total
    except Exception:
        return 0.0


def _scrape_masi_details_from_cb() -> dict:
    """
    Scrape MASI from https://www.casablanca-bourse.com/live-market/indices
    Returns dict with value, change_pct, change_ytd, volume.
    """
    html = _fetch_cb_page(CB_LIVE_INDICES_URL)
    details = _parse_masi_details_from_drupal_json(html)
    if details["value"] <= 0:
        soup = BeautifulSoup(html, "lxml")
        details = _parse_masi_details_from_html(soup)

    if details["value"] <= 0:
        raise RuntimeError("MASI index value not found on Casablanca Bourse indices page")

    # Indices JSON has no volume; use aggregate stock market volume as proxy.
    if details.get("volume", 0) <= 0:
        details["volume"] = _market_volume_from_actions()

    return details


@st.cache_data(ttl=60)
def _cached_fetch_masi_details() -> dict:
    try:
        return _scrape_masi_details_from_cb()
    except Exception as e:
        st.warning(f"⚠️ MASI indisponible: {e}")
        return _empty_masi_details()


def fetch_masi_details() -> dict:
    """
    Return live MASI details:
      {value, change_pct, change_ytd, volume}
    Numbers are plain floats suitable for calculations.
    """
    return _cached_fetch_masi_details()


def fetch_masi_from_cb() -> float:
    """Return the live MASI index value as a float (e.g. 18715.05)."""
    return float(fetch_masi_details().get("value") or 0.0)

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
            "variation": _safe_float(action.get("variation")),
            "volume": _safe_float(action.get("volume")),
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
                "variation": 0.0,
                "volume": 0.0,
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
                "variation": 0.0,
                "volume": 0.0,
            })

    return rows

def _scrape_cb_prices() -> pd.DataFrame:
    """
    Scrape Casablanca Bourse live market (Actions) and return DataFrame
    [valeur, cours, variation, volume] (+ symbol/name). Always appends Cash.
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
        df = pd.DataFrame(columns=["symbol", "name", "valeur", "cours", "variation", "volume"])

    if "variation" not in df.columns:
        df["variation"] = 0.0
    if "volume" not in df.columns:
        df["volume"] = 0.0

    cash_row = {
        "symbol": "CASH",
        "name": "Cash",
        "valeur": "Cash",
        "cours": 1.0,
        "variation": 0.0,
        "volume": 0.0,
    }
    df = pd.concat([df, pd.DataFrame([cash_row])], ignore_index=True)
    cols = [c for c in ("symbol", "name", "valeur", "cours", "variation", "volume") if c in df.columns]
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
        return _enrich_stocks_dataframe(out)

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
      1) Scrape Casablanca Bourse live market (Actions) for cours/variation/volume
      2) Save prices to Supabase (best-effort)
      3) On scrape failure, fall back to Supabase cache
    """
    try:
        df = _scrape_cb_prices()
        _upsert_prices_to_supabase(df)
        return _enrich_stocks_dataframe(df)
    except Exception as e:
        st.error(f"Failed to scrape Casablanca Bourse prices: {e}")
        df_db = _read_prices_from_supabase(max_age_seconds=SUPABASE_PRICES_MAX_AGE_SECONDS)
        if not df_db.empty and not _supabase_cache_looks_like_tickers(df_db):
            return _enrich_stocks_dataframe(df_db)
        df_db_any = _read_prices_from_supabase(max_age_seconds=10**9)
        if not df_db_any.empty:
            return _enrich_stocks_dataframe(df_db_any)
        return pd.DataFrame(columns=["symbol", "name", "valeur", "cours", "variation", "volume"])

def fetch_stocks() -> pd.DataFrame:
    """Return live/cached stocks [valeur, cours, variation, volume, symbol, name] + Cash."""
    return _enrich_stocks_dataframe(_cached_fetch_stocks())

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
