
# LightGBM training scaffold for district-level risk scoring.
# This script is a template: you'll need to provide a training dataset with features such as:
# district, date, cases_last_7, population, population_density, rainfall, mobility_index, etc.
# The script trains a simple LightGBM model and writes out a pickle model.

import pandas as pd
import lightgbm as lgb
import joblib
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score

# Load data - replace with your dataset path
df = pd.read_csv("training_data.csv")  # expects label column 'high_risk' (0/1)
features = [c for c in df.columns if c not in ['district','date','high_risk']]

X = df[features]
y = df['high_risk']

X_train, X_val, y_train, y_val = train_test_split(X,y,test_size=0.2,random_state=42)
train_data = lgb.Dataset(X_train, label=y_train)
val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)

params = {'objective':'binary','metric':'auc','verbosity':-1}
bst = lgb.train(params, train_data, valid_sets=[val_data], early_stopping_rounds=20, num_boost_round=500)
y_pred = bst.predict(X_val)
print("AUC:", roc_auc_score(y_val, y_pred))
joblib.dump(bst, "district_risk_model.pkl")
print("Saved model to district_risk_model.pkl")
