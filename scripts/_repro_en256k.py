"""Reproduce one failing case end-to-end and dump the fact_sheet."""
import os, sys, json
sys.path.insert(0, r'E:\MASE-demo'); sys.path.insert(0, r'E:\MASE-demo\src')
os.environ['MASE_CONFIG_PATH'] = r'E:\MASE-demo\config.dual_gpu.json'
os.environ['MASE_TASK_TYPE'] = 'long_context_qa'
os.environ['MASE_LVEVAL_DATASET'] = 'factrecall_en_256k'

from huggingface_hub import hf_hub_download
import zipfile
zp = hf_hub_download(repo_id='Infinigence/LVEval', repo_type='dataset', filename='factrecall_en.zip')
# Pick first sample (we just need ANY 256k case to study retrieval)
with zipfile.ZipFile(zp) as zf:
    with zf.open('factrecall_en/factrecall_en_256k.jsonl') as f:
        sample = json.loads(f.readline())
print('sample context_chars=', len(sample.get('context','')))
question = sample['input']
context = sample['context']
gold = sample['answers']
print('Q:', question[:200])
print('GOLD:', gold)
# Find planted sentence in context
import re
m = re.search(r'(?i)(ludwig\s+beethoven[^.]{0,200}\.)', context)
print('planted in context @', m.start() if m else 'NOT FOUND', ':', m.group(0)[:200] if m else '')

# Now drive MASE
import tempfile
mem = tempfile.mkdtemp(prefix='diag_en256k_')
os.environ['MASE_MEMORY_DIR'] = mem
from mase.engine import MASESystem
sys_obj = MASESystem()
# Ingest context
print('ingesting context...')
sys_obj.ingest_text(context)
print('asking...')
result = sys_obj.ask(question)
print('---ANSWER---'); print(result.get('answer'))
fs = (result.get('debug') or {}).get('fact_sheet') or result.get('fact_sheet') or ''
print('fact_sheet_len:', len(fs))
print('---FACT_SHEET (first 2000)---'); print(fs[:2000])
print('---FACT_SHEET (last 1000)---'); print(fs[-1000:])
beethoven_idx = fs.lower().find('beethoven')
print('beethoven_in_fact_sheet @', beethoven_idx)
if beethoven_idx >= 0:
    print('CTX:', fs[max(0,beethoven_idx-200):beethoven_idx+200])
