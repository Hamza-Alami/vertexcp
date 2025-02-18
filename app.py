# 💻 Full Steps & Complete Code for Supabase + Streamlit Portfolio App

## 🚀 1️⃣ **Create Supabase Tables:**
### **1. `clients` Table:**
- `name`: `text` (Primary Key)

### **2. `portfolios` Table:**
- `id`: `uuid` (Primary Key)
- `client_name`: `text` (Foreign Key from `clients`)
- `name`: `text` (Stock name)
- `quantity`: `integer`
- `value`: `float`
- `cash`: `float`

### **3. `stocks` Table:** *(For `cours` page)*
- `name`: `text` (Primary Key)
- `dernier_cours`: `float`

## 🔒 2️⃣ **Supabase Policies:**
- Enable **`INSERT`, `UPDATE`, `SELECT`** for all tables.

---
## 📝 3️⃣ **`requirements.txt`:**
```
streamlit==1.30.0
supabase==1.1.0
pandas==2.2.0
requests==2.31.0
```

## 🔑 4️⃣ **`secrets.toml` on Streamlit Cloud:**
```
[supabase]
url = "https://your-supabase-url"
key = "your-supabase-api-key"
```

---
## 🐍 5️⃣ **`app.py` Full Code:**
```python
import streamlit as st
import pandas as pd
import requests
from supabase import create_client

# Connect to Supabase
supabase = create_client(st.secrets['supabase']['url'], st.secrets['supabase']['key'])

# 📈 Load Stocks from API
@st.cache_data
def get_stocks():
    response = requests.get('https://backend.idbourse.com/api_2/get_all_data')
    data = response.json()
    stocks = pd.DataFrame([(item['name'], item['dernier_cours']) for item in data], columns=['name', 'dernier_cours'])
    stocks.loc[len(stocks)] = ['CASH', 1.0]
    return stocks

stocks = get_stocks()

# 🧑‍🤝‍🧑 Manage Clients
client_name = st.text_input("Client Name")
if st.button("Add Client"):
    supabase.table('clients').insert({"name": client_name}).execute()
    st.success(f"Client '{client_name}' added!")

# 📊 Show Clients
clients = [c['name'] for c in supabase.table('clients').select("name").execute().data]
selected_client = st.selectbox("Select Client", clients)

# 📊 Manage Client Portfolio
portfolio_data = supabase.table('portfolios').select("*").eq('client_name', selected_client).execute().data
portfolio_df = pd.DataFrame(portfolio_data)
st.data_editor(portfolio_df, num_rows="dynamic")
