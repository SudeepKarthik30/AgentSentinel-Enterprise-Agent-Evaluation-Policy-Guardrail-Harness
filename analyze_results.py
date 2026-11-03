import glob
import os
import csv
from collections import defaultdict

files = sorted(glob.glob('new_test_results/*.csv'))
for fpath in files:
    fname = os.path.basename(fpath)
    with open(fpath, encoding='utf-8-sig') as f:
        reader = list(csv.DictReader(f))
    
    total = len(reader)
    passed = sum(1 for r in reader if r.get('Overall Result') == 'PASS')
    tool_pass = sum(1 for r in reader if r.get('Tool Status') == 'PASS')
    ans_pass = sum(1 for r in reader if r.get('Answer Status') == 'PASS')
    arg_pass = sum(1 for r in reader if r.get('Argument Status') == 'PASS')
    claim_pass = sum(1 for r in reader if r.get('Claim Audit Status') == 'PASS')
    fin_halluc = sum(1 for r in reader if r.get('Financial Hallucination') == 'DETECTED')
    task_pass = sum(1 for r in reader if r.get('Task Status') == 'PASS')
    
    discrepancies = defaultdict(int)
    for r in reader:
        discrepancies[r.get('Claim Discrepancy', 'NONE')] += 1
        
    latencies = []
    for r in reader:
        val = r.get('Latency (ms)', '')
        try:
            latencies.append(float(val))
        except ValueError:
            pass
    avg_lat = sum(latencies)/len(latencies) if latencies else 0
    
    cat_stats = defaultdict(lambda: {'total': 0, 'pass': 0})
    for r in reader:
        cat = r.get('Category', 'Unknown')
        cat_stats[cat]['total'] += 1
        if r.get('Overall Result') == 'PASS':
            cat_stats[cat]['pass'] += 1

    print('='*80)
    print(f"FILE: {fname} (Total: {total})")
    print(f"Overall Pass Rate: {passed}/{total} ({passed/total*100:.1f}%)")
    print(f"Tool Correctness: {tool_pass}/{total} ({tool_pass/total*100:.1f}%)")
    print(f"Answer Correctness: {ans_pass}/{total} ({ans_pass/total*100:.1f}%)")
    print(f"Argument Correctness: {arg_pass}/{total} ({arg_pass/total*100:.1f}%)")
    print(f"Claim Audit Pass: {claim_pass}/{total} ({claim_pass/total*100:.1f}%)")
    print(f"Financial Hallucinations: {fin_halluc}/{total} ({fin_halluc/total*100:.1f}%)")
    print(f"Task Completion Pass: {task_pass}/{total} ({task_pass/total*100:.1f}%)")
    print(f"Avg Latency: {avg_lat:.1f} ms")
    print("Discrepancy Breakdown:", dict(discrepancies))
    print("Category Pass Rates:")
    for cat, s in sorted(cat_stats.items()):
        p_cnt = s['pass']
        t_cnt = s['total']
        pct = (p_cnt / t_cnt * 100) if t_cnt > 0 else 0
        print(f"  - {cat}: {p_cnt}/{t_cnt} ({pct:.1f}%)")
