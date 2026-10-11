# Fresh evaluation set

Owned by the teammate. Write `cases.json` here in the same format as `evals/dev/cases.json`, without looking at prompts or tuning against it. Do not use these cases in prompts or implementation decisions. Run once after the pipeline is frozen:

```
.venv/bin/python evals/run_eval.py --cases evals/fresh/cases.json
```

Report the sample size and concrete failures alongside any metric.
