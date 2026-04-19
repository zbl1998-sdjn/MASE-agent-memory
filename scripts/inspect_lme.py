"""Inspect a LongMemEval case end-to-end."""
import os, sys, json
sys.path.insert(0, r'E:\MASE-demo'); sys.path.insert(0, r'E:\MASE-demo\src')
os.environ.setdefault('MASE_CONFIG_PATH', r'E:\MASE-demo\config.json')

from benchmarks.registry import load_benchmark_samples
from benchmarks.runner import _ingest_turns_into_mase
from mase import MASESystem
import shutil

idx = int(sys.argv[1]) if len(sys.argv) > 1 else 0
samples = load_benchmark_samples('longmemeval_s', sample_limit=idx+1, path=r'E:\MASE-demo\data\longmemeval_official\longmemeval_s_500.json')
sample = samples[idx]
print('Q:', sample.question)
print('GT:', sample.ground_truth)
print('qtype:', sample.metadata.get('question_type'))
print('history_turns:', len(sample.history))
print()

case_dir = r'E:\MASE-demo\memory_runs\_inspect_lme'
if os.path.exists(case_dir): shutil.rmtree(case_dir)
os.makedirs(case_dir, exist_ok=True)
os.environ['MASE_MEMORY_DIR'] = case_dir
os.environ['MASE_TASK_TYPE'] = sample.task_type
os.environ.pop('MASE_LVEVAL_DATASET', None)
qd = (sample.metadata or {}).get('question_date') or ''
if qd:
    os.environ['MASE_QUESTION_REFERENCE_TIME'] = str(qd)

system = MASESystem()
_ingest_turns_into_mase(system, sample.history, benchmark_question_id=sample.id)

# Now run search directly to see what comes back
results = system.notetaker_agent.search(['__FULL_QUERY__'], full_query=sample.question, limit=10)
print('SEARCH HITS:', len(results))
for i, r in enumerate(results[:8], 1):
    c = (r.get('content') or '')[:200].replace('\n', ' | ')
    print(f'  [{i}] score={r.get("score")} {c}')
print()

# Run full pipeline
trace = system.run_with_trace(sample.question, log=False, forced_route={'action':'search_memory','keywords':['__FULL_QUERY__']})
print('ROUTE:', trace.route.action)
print('FACT_SHEET:')
print((trace.fact_sheet or '')[:1500])
print()
print('ANSWER:', trace.answer[:500])
