
"""
score_districts.py

A simple scoring script to compute weekly district risk scores.
If you have a trained model (district_risk_model.pkl) it will use it; otherwise
it will compute a naive score based on recent cases per population.

Outputs a CSV 'district_risk_scores.csv' with columns: district, date, score
"""
import pandas as pd
import os
import joblib
from utils import query_summary
from datetime import datetime, timedelta

OUT = "district_risk_scores.csv"
MODEL = "district_risk_model.pkl"

df = query_summary()
if df.empty:
    print("No cases to score.")
    raise SystemExit

# naive aggregation: cases per district in last 7 days
recent = df[df['onset_date'] >= (pd.Timestamp.now() - pd.Timedelta(days=7))]
agg = recent.groupby('district').size().rename('cases_7d').reset_index()
# load population if available
pop = None
if os.path.exists("district_population.csv"):
    pop = pd.read_csv("district_population.csv")
    agg = agg.merge(pop, on='district', how='left')
    agg['per_1000'] = agg['cases_7d'] / (agg['population']/1000)
else:
    agg['per_1000'] = agg['cases_7d']

# if model exists use it
if os.path.exists(MODEL):
    model = joblib.load(MODEL)
    features = [c for c in agg.columns if c not in ['district']]
    X = agg[features].fillna(0)
    preds = model.predict_proba(X)[:,1]
    agg['score'] = preds
else:
    # simple normalized score
    agg['score'] = agg['per_1000'] / (agg['per_1000'].max() if agg['per_1000'].max()>0 else 1)

agg['date'] = pd.Timestamp.now().strftime("%Y-%m-%d")
agg[['district','date','score']].to_csv(OUT, index=False)
print("Saved", OUT)
