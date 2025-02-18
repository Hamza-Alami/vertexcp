import streamlit as st
import requests
import pandas as pd
import numpy as np

# Load stock prices from API
@st.cache_data
def get_stock_data():
    url = "https://backend.idbourse.com/api_2/get_all_data"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        stocks = pd.DataFrame(data if isinstance(data, list) else data.get('stocks', []))
        stocks = stocks[['name', 'dernier_cours']]
        stocks = pd.concat([stocks, pd.DataFrame([{'name': 'CASH', 'dernier_cours': 1}])], ignore_index=True)
        return stocks
    st.error("Failed to load stock data")
    return pd.DataFrame()

stocks = get_stock_data()
st.title("📈 Stock Prices")
st.dataframe(stocks[['name', 'dernier_cours']])

# Clients Management
st.sidebar.title("👤 Clients")
if 'clients' not in st.session_state:
    st.session_state['clients'] = {}

client_name = st.sidebar.text_input("Client Name")
if st.sidebar.button("Add Client"):
    st.session_state['clients'][client_name] = pd.DataFrame(columns=["Valeur", "Quantité", "Cours", "Valorisation", "Target Weight", "Target Quantity", "Difference"])

for client, portfolio in st.session_state['clients'].items():
    st.subheader(f"Portfolio for {client}")
    if st.button(f"➕ Add Stock to {client}"):
        new_stock = st.selectbox(f"Select Stock for {client}", stocks['name'].tolist())
        new_row = pd.DataFrame({'Valeur': [new_stock], 'Quantité': [0], 'Cours': [stocks.loc[stocks['name'] == new_stock, 'dernier_cours'].values[0]], 'Valorisation': [0], 'Target Weight': [0], 'Target Quantity': [0], 'Difference': [0]})
        st.session_state['clients'][client] = pd.concat([portfolio, new_row], ignore_index=True)

    # Automatic Calculation of Portfolio Values
    portfolio['Cours'] = portfolio['Valeur'].map(stocks.set_index('name')['dernier_cours'])
    portfolio['Valorisation'] = portfolio['Quantité'] * portfolio['Cours']
    valorisation_totale = portfolio['Valorisation'].sum()
    portfolio['Target Quantity'] = (portfolio['Target Weight'] * valorisation_totale / portfolio['Cours']).fillna(0)
    portfolio['Difference'] = np.floor(portfolio['Quantité'] - portfolio['Target Quantity'])

    edited_portfolio = st.data_editor(portfolio, num_rows="dynamic")
    st.session_state['clients'][client] = edited_portfolio
    st.write(f"Total Portfolio Value: {valorisation_totale:.2f}")
    
    if st.button(f"Delete {client}"):
        del st.session_state['clients'][client]
        st.success(f"Client '{client}' deleted")

# Inventaire Section
st.title("📊 Inventaire")
inventaire = pd.DataFrame(columns=["Valeur", "Quantité Totale"])
for data in st.session_state['clients'].values():
    grouped = data.groupby('Valeur')['Quantité'].sum().reset_index()
    inventaire = pd.concat([inventaire, grouped])
inventaire = inventaire.groupby('Valeur')['Quantité'].sum().reset_index()
st.dataframe(inventaire)
