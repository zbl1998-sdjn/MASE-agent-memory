# External Generalization Failure Reports

Use this report after BAMBOO or NoLiMa runs to keep external generalization
debugging separate from benchmark-specific score chasing.

## Generate

```powershell
python scripts/benchmarks/summarize_external_failures.py `
  --input E:\MASE-runs\external-benchmarks\BAMBOO\outputs\<run>\senhallu.details.json `
  --input E:\MASE-runs\external-benchmarks\NoLiMa\outputs\<run>\nolima.results.json `
  --output E:\MASE-runs\results\generalization-regression\failure-report.md `
  --json-output E:\MASE-runs\results\generalization-regression\failure-report.json
```

## Buckets

- `model_backend_error`: provider, network, timeout, rate limit, or HTTP status errors.
- `adapter_error`: runner or adapter exception that is not clearly a model backend failure.
- `format_failure`: model returned something that the task parser cannot use.
- `model_refusal_or_evidence_miss`: abstention-like answer; inspect evidence before treating it as retrieval failure.
- `empty_response`: no error and no usable model text.
- `answer_mismatch_or_reasoning_failure`: scored failure with a non-empty answer.
- `unscored_failure`: row has no clear scoring signal.
- `passed`: row already passed and is included for denominator clarity.

The bucket names are intentionally conservative. For example, refusals are not
automatically labeled as retrieval failures because the same symptom can come
from missing evidence, prompt mismatch, or model conservatism.
