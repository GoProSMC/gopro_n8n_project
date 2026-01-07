import pandas as pd
import os

file_path = 'data/signals.xlsx'

# Create a DataFrame with the required columns
df = pd.DataFrame(columns=['symbol', 'key', 'type', 'created_at', 'date', 'threshold', 'signal', 'reasoning'])

# Write to Excel
df.to_excel(file_path, sheet_name='signals', index=False)
print(f"Reset {file_path} with headers only.")
