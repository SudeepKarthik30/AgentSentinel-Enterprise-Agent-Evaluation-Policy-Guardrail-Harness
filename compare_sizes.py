import glob
import os

print(f"{'CHAPTER':<35} {'PREVIOUS BYTES':<15} {'CURRENT BYTES':<15} {'RATIO':<10}")
print("-" * 75)

prev_files = sorted(glob.glob('collage_Report/previous_report_extracted/chapters/*.tex'))
curr_files = sorted(glob.glob('collage_Report/chapters/*.tex'))

total_prev = 0
total_curr = 0

for pf, cf in zip(prev_files, curr_files):
    name = os.path.basename(pf)
    p_len = os.path.getsize(pf)
    c_len = os.path.getsize(cf)
    total_prev += p_len
    total_curr += c_len
    ratio = c_len / p_len if p_len else 0
    print(f"{name:<35} {p_len:<15} {c_len:<15} {ratio:.2f}")

print("-" * 75)
print(f"{'TOTALS':<35} {total_prev:<15} {total_curr:<15} {total_curr/total_prev:.2f}")
