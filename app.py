import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timezone
st.set_page_config(page_title="Crypto & Equities", layout="wide")
st.title("Crypto & Equities Dashboard")
def secret(k):
    try: return str(st.secrets.get(k, "")).strip()
    except Exception: return ""
pw = secret("DASHBOARD_PASSWORD")
if not pw:
    st.error("Set DASHBOARD_PASSWORD, CMC_API_KEY and TWELVE_DATA_API_KEY in hosting Secrets.")
    st.stop()
if st.text_input("Password", type="password") != pw: st.stop()
cmc, td = secret("CMC_API_KEY"), secret("TWELVE_DATA_API_KEY")
if not cmc or not td:
    st.error("Missing API keys in hosting Secrets.")
    st.stop()
@st.cache_data(ttl=60)
def get_crypto(key):
    r = requests.get("https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest", headers={"X-CMC_PRO_API_KEY": key}, params={"symbol":"BTC,ETH,SOL,LINK,XLM,SUI,HYPE","convert":"USD"}, timeout=15)
    r.raise_for_status(); d = r.json()
    if d.get("status", {}).get("error_code", 0): raise RuntimeError(d["status"].get("error_message","CMC error"))
    rows=[]
    for s in ["BTC","ETH","SOL","LINK","XLM","SUI","HYPE"]:
        v=d.get("data",{}).get(s,[])
        if isinstance(v,dict): v=[v]
        q=(v[0].get("quote",{}).get("USD",{}) if v else {})
        rows.append({"Asset":s,"Price USD":q.get("price"),"24h %":q.get("percent_change_24h"),"Updated":q.get("last_updated"),"Source":"CoinMarketCap"})
    return rows
@st.cache_data(ttl=60)
def get_quote(symbol, key):
    r=requests.get("https://api.twelvedata.com/quote",params={"symbol":symbol,"apikey":key},timeout=15); r.raise_for_status(); d=r.json()
    if d.get("status")=="error" or "code" in d: raise RuntimeError(d.get("message","Twelve Data error"))
    p=d.get("close") or d.get("price")
    return {"Asset":symbol,"Price USD":float(p) if p else None,"24h %":float(d["percent_change"]) if d.get("percent_change") else None,"Updated":d.get("datetime"),"Source":"Twelve Data"}
if st.button("Refresh now"): get_crypto.clear(); get_quote.clear()
st.caption("Checked at "+datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"))
st.subheader("Crypto · CoinMarketCap")
try: st.dataframe(pd.DataFrame(get_crypto(cmc)), use_container_width=True, hide_index=True)
except Exception as e: st.error("CMC request failed: "+str(e))
st.subheader("Stocks and ETFs · Twelve Data")
syms=st.multiselect("Symbols",["AAPL","MSFT","NVDA","GOOGL","AMZN","META","TSLA","SPY","QQQ"],["AAPL","MSFT","NVDA","SPY","QQQ"])
rows=[]
for s in syms:
    try: rows.append(get_quote(s,td))
    except Exception as e: st.warning(s+": "+str(e))
if rows: st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True)
st.caption("Informational snapshots only. Source timestamps may differ. No trade execution.")
