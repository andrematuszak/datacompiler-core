# eval_deepseek.py
from lm_eval import evaluator, tasks
from lm_eval.models.ollama import OllamaLM

model = OllamaLM(
    model="deepseek-coder:6.7b",
    base_url="http://localhost:11434"
)

results = evaluator.evaluate(
    model=model,
    tasks=tasks.get_task_dict(["hellaswag", "arc_easy"]),
    limit=20
)

print(results)