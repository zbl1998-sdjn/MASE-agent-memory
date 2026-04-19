import os, sys, json, shutil
sys.path.insert(0, r'E:\MASE-demo'); sys.path.insert(0, r'E:\MASE-demo\src')
os.environ.setdefault('MASE_CONFIG_PATH', r'E:\MASE-demo\config.json')
from benchmarks.registry import load_benchmark_samples
from benchmarks.runner import _ingest_turns_into_mase
from mase import MASESystem
PATH = r'E:\MASE-demo\data\longmemeval_official\longmemeval_s_500.json'
all_data = json.load(open(PATH,encoding='utf-8'))
target_idx = next(i for i,r in enumerate(all_data) if r['question'].startswith('What was the discount'))
samples = load_benchmark_samples('longmemeval_s', sample_limit=target_idx+1, path=PATH)
sample = samples[target_idx]
case_dir = r'E:\MASE-demo\memory_runs\_inspect_lme'
if os.path.exists(case_dir): shutil.rmtree(case_dir)
os.makedirs(case_dir, exist_ok=True)
os.environ['MASE_MEMORY_DIR']=case_dir
os.environ['MASE_TASK_TYPE']=sample.task_type
qd = (sample.metadata or {}).get('question_date') or ''
if qd: os.environ['MASE_QUESTION_REFERENCE_TIME']=str(qd)
system = MASESystem()
_ingest_turns_into_mase(system, sample.history, benchmark_question_id=sample.id)
trace = system.run_with_trace(sample.question)
print('ANSWER:', trace.answer)
print('GT:', sample.ground_truth)
