import streamlit as st
import requests
import pandas as pd
import json

# Load stock prices from API with proper response parsing
@st.cache_data
def get_stock_data():
    url = "https://backend.idbourse.com/api_2/get_all_data"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        if isinstance(data, list):
            stocks = pd.DataFrame(data)
        elif isinstance(data, dict) and 'stocks' in data:
            stocks = pd.DataFrame(data['stocks'])
        else:
            st.error("Invalid API response format")
            return pd.DataFrame()
        stocks = pd.concat([stocks, pd.DataFrame([{'name': 'CASH', 'dernier_cours': 1}])], ignore_index=True)
        return stocks
    else:
        st.error("Failed to load stock data")
        return pd.DataFrame()

stocks = get_stock_data()
st.title("📈 Stock Prices")
st.dataframe(stocks)

# Strategies Management
st.sidebar.title("🎯 Strategies")
if 'strategies' not in st.session_state:
    st.session_state['strategies'] = {}

strategy_name = st.sidebar.text_input("Strategy Name")
new_weight = st.sidebar.slider("CASH Weight Adjustment (%)", 0, 100, 0)

if st.sidebar.button("Create Strategy"):
    if strategy_name:
        st.session_state['strategies'][strategy_name] = {'stocks': {}, 'cash_weight': new_weight}
        st.success(f"Strategy '{strategy_name}' created")
    else:
        st.error("Please enter a strategy name")

for name, strategy in st.session_state['strategies'].items():
    st.sidebar.subheader(name)
    st.sidebar.write(strategy)

# Clients Management
st.sidebar.title("👤 Clients")
if 'clients' not in st.session_state:
    st.session_state['clients'] = {}

client_name = st.sidebar.text_input("Client Name")
if st.sidebar.button("Add Client"):
    if client_name:
        st.session_state['clients'][client_name] = pd.DataFrame(columns=["Valeur", "Quantité", "Cours", "Valorisation", "Poids", "Poids cible", "Quantité cible", "Écart"])
        st.success(f"Client '{client_name}' added")
    else:
        st.error("Please enter a client name")

st.title("📂 Client Portfolios")
for client, portfolio in st.session_state['clients'].items():
    st.subheader(f"Portfolio: {client}")
    st.dataframe(portfolio)

# Inventaire
st.title("📊 Inventaire")
inventaire = pd.DataFrame(columns=["Valeur", "Quantité Totale"])
for client, portfolio in st.session_state['clients'].items():
    if not portfolio.empty:
        portfolio_grouped = portfolio.groupby('Valeur')['Quantité'].sum().reset_index()
        inventaire = pd.concat([inventaire, portfolio_grouped])
inventaire = inventaire.groupby('Valeur')['Quantité'].sum().reset_index()
st.dataframe(inventaire)
