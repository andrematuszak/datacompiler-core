# eval_deepseek.py
import json
import os
from datetime import datetime
from lm_eval import evaluator, tasks
from lm_eval.models.ollama import OllamaLM

# Configuration
MODEL_NAME = "deepseek-coder:6.7b"
TASKS = ["hellaswag", "arc_easy", "gsm8k"]
LIMIT = 20  # Mettre à None pour tout évaluer

# Créer un dossier pour les résultats
os.makedirs("resultats", exist_ok=True)

print(f"🚀 Évaluation de {MODEL_NAME} dans {os.getcwd()}")

# Charger le modèle
model = OllamaLM(
    model=MODEL_NAME,
    base_url="http://localhost:11434"
)

# Évaluation
results = evaluator.evaluate(
    model=model,
    tasks=tasks.get_task_dict(TASKS),
    limit=LIMIT
)

# Sauvegarder avec timestamp
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
filename = f"resultats/resultats_{timestamp}.json"

with open(filename, "w") as f:
    json.dump(results, f, indent=2, default=str)

print(f"✅ Résultats sauvegardés dans {filename}")

# Afficher un résumé
print("\n📊 RÉSUMÉ :")
for task_name, task_results in results["results"].items():
    acc = task_results.get("acc", None)
    if acc:
        print(f"  {task_name}: {acc:.2%}")
        