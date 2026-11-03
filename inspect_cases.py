import csv
import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('new_test_results/agent_eval_benchmark_20_NetworkDrops_withEffectGuard_2026-11-02_00-13-20.csv', encoding='utf-8-sig') as f:
    reader = list(csv.DictReader(f))

for r in reader:
    if r.get('Case Index') in ['12', '14', '15']:
        print('='*75)
        print(f"CASE {r.get('Case Index')}: Category={r.get('Category')}")
        print("Input:", r.get('Input Query'))
        print("Expected:", r.get('Expected Output'))
        print("Actual:", r.get('Actual Output'))
        print("Tools Called:", r.get('Tools Called'))
        print("Claim Discrepancy:", r.get('Claim Discrepancy'))
        print("Financial Hallucination:", r.get('Financial Hallucination'))
        print("Error:", r.get('Error'))
