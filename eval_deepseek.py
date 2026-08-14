import json
import requests  # Module HTTP
from lm_eval import evaluator
from lm_eval.api.model import LM
import time
import sys

class OllamaDirect(LM):
    """Wrapper direct pour Ollama - sans torch ni transformers !"""
    
    def __init__(self, model="deepseek-coder:6.7b", base_url="http://localhost:11434"):
        super().__init__()
        self.model_name = model
        self.base_url = base_url
        
    # 🔥 CORRECTION 1 : Renommer l'argument pour ne pas écraser le module 'requests'
    def generate_until(self, instances: list) -> list[str]:
        """Génère des réponses via l'API Ollama"""
        results = []
        total = len(instances)
        
        for idx, instance in enumerate(instances):
            # 🔥 CORRECTION 2 : Extraction correcte depuis l'objet Instance de lm-eval
# 🔥 CORRECTION : Extraction depuis le tuple args
            if hasattr(instance, 'args'): 
                prompt = instance.args[0]
                
                # Les options sont dans le 2ème élément de args s'il existe
                gen_kwargs = instance.args[1] if len(instance.args) > 1 and isinstance(instance.args[1], dict) else {}
                
                until = gen_kwargs.get('until', ["\n\n", "\n", "###"])
                max_tokens = gen_kwargs.get('max_gen_toks', 256)
                temperature = gen_kwargs.get('temperature', 0.0)
            else:  # Fallback pour de très vieilles versions
                prompt = instance[0] if isinstance(instance, (list, tuple)) else str(instance)
                until = ["\n\n", "\n", "###"]
                max_tokens = 256
                temperature = 0.0
            
            try:
                # Appel à l'API Ollama (fonctionne maintenant car le module 'requests' est préservé)
                response = requests.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": self.model_name,
                        "prompt": prompt,
                        "stream": False,
                        "options": {
                            "num_predict": max_tokens,
                            "temperature": temperature,
                            "top_p": 0.95,
                            "stop": until
                        }
                    },
                    timeout=120
                )
                
                if response.status_code == 200:
                    result = response.json().get("response", "")
                    # Couper au premier token d'arrêt par sécurité
                    for stop in until:
                        if stop and stop in result:
                            result = result.split(stop)[0]
                    results.append(result.strip())
                else:
                    print(f"⚠️ Erreur API: {response.status_code}")
                    results.append("")
                    
            except Exception as e:
                print(f"⚠️ Erreur sur l'exemple {idx+1}/{total}: {e}")
                results.append("")
                
            # Afficher la progression
            if (idx + 1) % 5 == 0:
                print(f"  Progression: {idx+1}/{total}")
                
            time.sleep(0.1)  # Léger délai pour ne pas saturer l'API locale
            
        return results
    
    def loglikelihood(self, instances):
        """Retourne des zéros. Voir l'avertissement plus bas."""
        return [(0.0, False)] * len(instances)
    
    def loglikelihood_rolling(self, instances):
        return [(0.0, False)] * len(instances)

# ============================================
# CONFIGURATION
# ============================================

MODEL_NAME = "deepseek-coder:6.7b"
# 🔥 CORRECTION 3 : J'ai retiré hellaswag et arc_easy qui ne fonctionnent pas sans loglikelihood (voir note plus bas)
TASKS = ["gsm8k"] 
LIMIT = 20

print("=" * 60)
print("🚀 ÉVALUATION DEEPSEEK AVEC HARNESS (WRAPPER OLLAMA)")
print("=" * 60)

# 1. Vérifier Ollama
print("\n🔍 Vérification de Ollama...")
try:
    response = requests.get("http://localhost:11434/api/tags")
    if response.status_code == 200:
        models = response.json().get("models", [])
        if any(m.get("name") == MODEL_NAME for m in models):
            print(f"✅ Modèle {MODEL_NAME} trouvé")
        else:
            print(f"❌ Modèle {MODEL_NAME} non trouvé")
            print(f"   Modèles disponibles: {[m.get('name') for m in models]}")
            sys.exit(1)
    else:
        print("❌ Ollama ne répond pas")
        sys.exit(1)
except Exception as e:
    print(f"❌ Erreur: {e}")
    sys.exit(1)

# 2. Initialiser le modèle
print(f"\n📦 Chargement du modèle custom: {MODEL_NAME}")
model = OllamaDirect(model=MODEL_NAME)

# 3. Lancer l'évaluation
print(f"\n⏳ Évaluation en cours ({LIMIT} exemples par tâche)...")

start_time = time.time()

# 🔥 CORRECTION 4 : Utiliser simple_evaluate (l'API gère le TaskManager en interne)
results = evaluator.simple_evaluate(
    model=model,
    tasks=TASKS,
    limit=LIMIT
)

end_time = time.time()

# 4. Afficher les résultats
print("\n" + "=" * 60)
print("📊 RÉSULTATS DE L'ÉVALUATION")
print("=" * 60)

if "results" in results:
    for task_name, task_results in results["results"].items():
        if isinstance(task_results, dict):
            print(f"\n📌 {task_name}:")
            for metric, value in task_results.items():
                if isinstance(value, (int, float)):
                    if metric in ["acc", "acc_norm", "f1", "exact_match"]:
                        print(f"   {metric:12}: {value:.2%}")
                    else:
                        print(f"   {metric:12}: {value:.4f}")

# 5. Sauvegarder
timestamp = time.strftime("%Y%m%d_%H%M%S")
filename = f"resultats_deepseek_{timestamp}.json"

with open(filename, "w") as f:
    json.dump(results, f, indent=2, default=str)

print(f"\n💾 Résultats sauvegardés dans: {filename}")
print(f"⏱️  Temps total: {end_time - start_time:.1f} secondes")