"""Une vraie question BM25 avec Qwen/Ollama, sans import du pipeline Groq."""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from uuid import uuid4

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--question', default='q01')
    parser.add_argument('--model', default='qwen3:1.7b')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    from app.retriever import search
    cfg = yaml.safe_load((ROOT/'config.yaml').read_text(encoding='utf-8-sig'))
    cases = [json.loads(line) for line in (ROOT/'eval/testset.jsonl').read_text(encoding='utf-8-sig').splitlines() if line.strip()]
    matches = [case for case in cases if case['id'] == args.question]
    if len(matches) != 1:
        raise ValueError('Question absente ou non unique.')
    case = matches[0]
    system = (ROOT/cfg['prompt_file']).read_text(encoding='utf-8')
    sources = search(case['question'], k=cfg['retrieval']['top_k'], dossier=str(ROOT/'data/docs'))
    context = '\n\n'.join(f"[{s['id']}] {s['text']}" for s in sources)

    # Fenêtre explicite : ne pas dépendre du réglage implicite d'Ollama.
    num_ctx = 16384
    num_predict = 256
    payload = {
        'model': args.model,
        'messages': [
            {'role':'system','content':system},
            {'role':'user','content':f'<sources>\n{context}\n</sources>\n\nQuestion: {case["question"]}'},
        ],
        'stream': False,
        'think': False,
        'options': {'temperature':0, 'num_ctx':num_ctx, 'num_predict':num_predict},
    }
    print('Modèle local :',args.model)
    print('Question :',case['id'])
    print('Sources :',[s['id'] for s in sources])
    print('Contexte documentaire :',len(context),'caractères')
    print('Fenêtre configurée :',num_ctx,'tokens')
    if args.dry_run:
        print('Préparation terminée : aucun appel réseau, aucun fichier créé.')
        return

    request = Request(
        'http://localhost:11434/api/chat',
        data=json.dumps(payload,ensure_ascii=False).encode('utf-8'),
        headers={'Content-Type':'application/json'},
        method='POST',
    )
    print('Génération locale en cours. Le premier chargement peut être lent.',flush=True)
    start=time.perf_counter()
    with urlopen(request,timeout=600) as response:
        raw=json.loads(response.read().decode('utf-8'))
    elapsed=round(time.perf_counter()-start,2)
    if raw.get('error'):
        raise RuntimeError(raw['error'])
    answer=raw.get('message',{}).get('content','').strip()
    folder=ROOT/'eval/results/local_smoke'
    folder.mkdir(parents=True,exist_ok=True)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
    output=folder/f'{stamp}_{uuid4().hex[:8]}.json'
    record={
        'backend':'ollama_local','model':args.model,
        'tested_at_utc':datetime.now(timezone.utc).isoformat(),
        'purpose':'Essai de faisabilité baseline locale, pas un test du bouclier.',
        'case':case,'request':payload,'retrieved_passages':sources,
        'answer':answer,'seconds':elapsed,
        'runtime_metrics':{key:raw.get(key) for key in (
            'model','done','done_reason','prompt_eval_count','eval_count',
            'total_duration','load_duration','prompt_eval_duration','eval_duration',
        )},
        'review':'pending',
    }
    with output.open('x',encoding='utf-8') as file:
        json.dump(record,file,ensure_ascii=False,indent=2)
    print('Réponse :',answer or '[VIDE]')
    print('Référence :',case['answer'])
    print('Durée :',elapsed,'secondes')
    print('Fin de génération :',raw.get('done_reason'))
    print('Tokens du contexte évalué :',raw.get('prompt_eval_count'))
    print('Preuve :',output)
    if raw.get('done_reason')=='length':
        print('ATTENTION : génération tronquée, ne pas noter comme réponse complète.')
    if (raw.get('prompt_eval_count') or 0)+num_predict>=num_ctx:
        print('ATTENTION : contexte proche de la limite, vérifier toute troncature.')
    print('Aucun appel Groq. Aucun changement de config.yaml, du bouclier ou des documents.')


if __name__=='__main__':main()
