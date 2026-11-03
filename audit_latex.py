import re
import glob
from collections import Counter

bib_file = 'collage_Report/report.bib'
with open(bib_file, encoding='utf-8') as f:
    bib_text = f.read()
bib_keys = set(re.findall(r'@\w+\{([^,]+),', bib_text))
print(f'Total BibTeX entries: {len(bib_keys)}')

tex_files = glob.glob('collage_Report/chapters/*.tex') + ['collage_Report/report.tex']
all_citations = set()
all_labels = set()
all_refs = set()

for tf in sorted(tex_files):
    with open(tf, encoding='utf-8') as f:
        content = f.read()
    
    # Check environments
    begins = re.findall(r'\\begin\{([^}]+)\}', content)
    ends = re.findall(r'\\end\{([^}]+)\}', content)
    b_count = Counter(begins)
    e_count = Counter(ends)
    mismatches = []
    for env in set(b_count.keys()).union(e_count.keys()):
        if b_count[env] != e_count[env]:
            mismatches.append((env, b_count[env], e_count[env]))
    
    if mismatches:
        print(f'MISMATCH in {tf}:')
        for env, bc, ec in mismatches:
            print(f'   Env "{env}": begin={bc}, end={ec}')
    else:
        print(f'OK: Environments in {tf} (Count: {len(begins)})')

    # Citations
    cites = re.findall(r'\\cite\{([^}]+)\}', content)
    for c in cites:
        for k in c.split(','):
            all_citations.add(k.strip())
            
    # Labels and refs
    labels = re.findall(r'\\label\{([^}]+)\}', content)
    all_labels.update(labels)
    refs = re.findall(r'\\ref\{([^}]+)\}', content)
    all_refs.update(refs)

missing_cites = all_citations - bib_keys
if missing_cites:
    print('MISSING CITATIONS in .bib:', missing_cites)
else:
    print(f'ALL CITATIONS VERIFIED! (Count: {len(all_citations)})')

missing_refs = all_refs - all_labels
if missing_refs:
    print('MISSING REFS in labels:', missing_refs)
else:
    print(f'ALL REFS VERIFIED! (Count: {len(all_refs)})')
