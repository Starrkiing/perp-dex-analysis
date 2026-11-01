"""Rolling 14-day correlations. Sources: CoinGecko /coins/{id}/market_chart (daily, days=200) and
DeFiLlama perps protocol pages (defillama.com/protocol/perps/{slug}, __NEXT_DATA__ pageProps.chart = daily perp volume).
Outputs CSVs in the working directory (the repo stores them under data/)."""
import json,re,time,subprocess,csv,math
import pandas as pd
CG=['bitcoin','hyperliquid','lighter','edgex','dydx-chain','gmx','aster-2']
SYM={'bitcoin':'BTC','hyperliquid':'HYPE','lighter':'LIT','edgex':'EDGE','dydx-chain':'DYDX','gmx':'GMX','aster-2':'ASTER'}
def get(u):
    return subprocess.run(['curl','-sL','-A','Mozilla/5.0',u],capture_output=True,text=True).stdout
px={}
for i in CG:
    d=json.loads(get(f'https://api.coingecko.com/api/v3/coins/{i}/market_chart?vs_currency=usd&days=200&interval=daily'))
    s=pd.Series({pd.to_datetime(t,unit='ms').normalize():p for t,p in d['prices']})
    px[SYM[i]]=s[~s.index.duplicated(keep='first')]; time.sleep(2)
P=pd.DataFrame(px).sort_index(); P.to_csv('prices_daily.csv')
R=P.pct_change(fill_method=None)
pairs=[('HYPE','BTC'),('LIT','BTC'),('EDGE','BTC'),('DYDX','BTC'),('GMX','BTC'),('ASTER','BTC'),('HYPE','LIT'),('HYPE','DYDX')]
C=pd.DataFrame({f'{a}/{b}':R[a].rolling(14,min_periods=14).corr(R[b]) for a,b in pairs})
C.tail(183).to_csv('price_corr_14d.csv')
V={}
for slug in ['hyperliquid','variational','lighter','aster','gmx','edgex','grvt','pacifica','extended','dydx']:
    h=get(f'https://defillama.com/protocol/perps/{slug}')
    m=re.search(r'__NEXT_DATA__"[^>]*>(.*?)</script>',h,re.S)
    try: c=json.loads(m.group(1))['props']['pageProps']['chart']
    except Exception: print('unavailable',slug); continue
    V[slug]=pd.Series({pd.to_datetime(t,unit='ms'):v for t,v in c})
    time.sleep(1)
Vd=pd.DataFrame(V).sort_index().iloc[:-1]  # drop partial latest day
Vd.to_csv('perp_volume_daily.csv')
dV=Vd.where(Vd>0).pct_change(fill_method=None)
VC=pd.DataFrame({f'HL/{s}':dV['hyperliquid'].rolling(14,min_periods=14).corr(dV[s]) for s in V if s!='hyperliquid'})
VC.tail(183).to_csv('volume_change_corr_14d.csv')
print(C.tail(183).describe().T[['count','mean','min','max']]); print(VC.tail(183).describe().T[['count','mean','min','max']])
print(C.dropna(how='all').index.min(), C.index.max(), VC.index.max())
