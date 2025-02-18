import streamlit as st
import requests
import pandas as pd
import json

# Load stock prices from API
@st.cache_data
def get_stock_data():
    url = "https://backend.idbourse.com/api_2/get_all_data"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        if isinstance(data, (list, dict)):
            stocks = pd.DataFrame(data if isinstance(data, list) else data.get('stocks', []))
            stocks = stocks[['name', 'dernier_cours']]
            stocks = pd.concat([stocks, pd.DataFrame([{'name': 'CASH', 'dernier_cours': 1}])], ignore_index=True)
            return stocks
    st.error("Failed to load stock data")
    return pd.DataFrame()

stocks = get_stock_data()
st.title("📈 Stock Prices")
st.dataframe(stocks)

# Strategies Management
st.sidebar.title("🎯 Manage Strategies")
if 'strategies' not in st.session_state:
    st.session_state['strategies'] = {}

strategy_name = st.sidebar.text_input("Strategy Name")
selected_stocks = st.sidebar.multiselect("Select Stocks", stocks['name'].tolist())
weights = {stock: st.sidebar.slider(f"Weight for {stock} (%)", 0, 100, 0) for stock in selected_stocks}
cash_weight = 100 - sum(weights.values())

if st.sidebar.button("Save Strategy"):
    if strategy_name and cash_weight >= 0:
        weights['CASH'] = cash_weight
        st.session_state['strategies'][strategy_name] = weights
        st.success(f"Strategy '{strategy_name}' saved")
    else:
        st.error("Invalid strategy configuration")

st.sidebar.subheader("Saved Strategies")
for name, strategy in st.session_state['strategies'].items():
    st.sidebar.write(f"**{name}:** {strategy}")

# Clients Management
st.sidebar.title("👤 Clients")
if 'clients' not in st.session_state:
    st.session_state['clients'] = {}

client_name = st.sidebar.text_input("Client Name")
strategy_for_client = st.sidebar.selectbox("Select Strategy", list(st.session_state['strategies'].keys()))
if st.sidebar.button("Add Client"):
    if client_name and strategy_for_client:
        client_portfolio = pd.DataFrame(columns=["Valeur", "Quantité", "Cours", "Target Weight", "Target Quantity", "Difference"])
        strategy_weights = st.session_state['strategies'][strategy_for_client]
        for stock, weight in strategy_weights.items():
            client_portfolio = pd.concat([client_portfolio, pd.DataFrame({'Valeur': [stock], 'Target Weight': [weight]})], ignore_index=True)
        st.session_state['clients'][client_name] = {'portfolio': client_portfolio, 'strategy': strategy_for_client}
        st.success(f"Client '{client_name}' added with strategy '{strategy_for_client}'")
    else:
        st.error("Please enter a client name and select a strategy")

st.title("📂 Client Portfolios")
for client, data in st.session_state['clients'].items():
    st.subheader(f"Portfolio for {client} (Strategy: {data['strategy']})")
    data['portfolio']['Cours'] = data['portfolio']['Valeur'].map(stocks.set_index('name')['dernier_cours'])
    data['portfolio']['Target Quantity'] = (data['portfolio']['Target Weight'] * 1000) / data['portfolio']['Cours']  # Example scaling factor
    data['portfolio']['Difference'] = data['portfolio']['Quantité'].fillna(0) - data['portfolio']['Target Quantity']
    st.dataframe(data['portfolio'])
    if st.button(f"Delete {client}"):
        del st.session_state['clients'][client]
        st.success(f"Client '{client}' deleted")

st.title("📊 Inventaire")
inventaire = pd.DataFrame(columns=["Valeur", "Quantité Totale"])
for data in st.session_state['clients'].values():
    portfolio = data['portfolio']
    if not portfolio.empty:
        grouped = portfolio.groupby('Valeur')['Quantité'].sum().reset_index()
        inventaire = pd.concat([inventaire, grouped])
inventaire = inventaire.groupby('Valeur')['Quantité'].sum().reset_index()
st.dataframe(inventaire)
