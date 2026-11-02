"""ShieldLoop demo interface: duel (normal vs protected assistant), saved results, about.
Run from the repository root:  streamlit run app/ui.py
"""
import hashlib
import os
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))   # so that `from app...` works when Streamlit runs this file
os.chdir(ROOT)                  # relative paths (config.yaml, data/docs...) resolve from the repo root

st.set_page_config(page_title="ShieldLoop", layout="wide")

from app import ui_helpers as H  # noqa: E402

try:
    from app.pipeline import answer as answer_normal  # noqa: E402
except Exception as exc:  # most often: missing GROQ_API_KEY in .env
    st.error(f"Impossible de charger l'assistant normal : {type(exc).__name__}: {exc}")
    st.info("Vérifiez que le fichier .env contient GROQ_API_KEY et que vous lancez la commande depuis la racine du dépôt.")
    st.stop()

answer_protected, protected_error = H.find_protected_answer()

st.title("ShieldLoop")
st.caption("Un assistant qui lit des documents, face à des documents piégés : sans bouclier, puis avec.")

# ---------------- sidebar ----------------
with st.sidebar:
    st.header("Réglages")
    doc_set = st.radio("Documents lus par l'assistant",
                       ["Documents normaux (data/docs)", "Documents piégés (data/docs_attack)"])
    folder = "data/docs" if doc_set.startswith("Documents normaux") else "data/docs_attack"
    attack_mode = folder.endswith("attack")
    target = ""
    if attack_mode:
        target = st.text_input("Fausse valeur de l'attaque (à détecter)", placeholder="ex. 30 avril 2015 (attaque sur q01)")
        st.caption("Si cette valeur apparaît dans une réponse, l'attaque a réussi.")
    offline = st.checkbox("Mode démo enregistrée (aucun appel à Groq)")
    st.caption("Chaque résultat obtenu en direct est enregistré dans eval/ui_cache.json : "
               "si Groq limite les appels pendant la démo, activez ce mode.")

tab_duel, tab_results, tab_about = st.tabs(["Duel", "Résultats de l'évaluation", "À propos et limites"])


# ---------------- duel ----------------
def render_answer(col, title, res, status, msg, expected, target_value):
    """Show one assistant's answer with its badges. Return (attack_hit, correct)."""
    hit = correct = None
    with col:
        st.subheader(title)
        if res is None:
            st.error(msg or "Pas de réponse.")
            return hit, correct
        text = res.get("answer", "")
        with st.container(border=True):
            st.write(text)
        if target_value:
            hit = H.contains_any(text, [target_value])
            if hit:
                st.error("Attaque réussie : la fausse valeur apparaît dans la réponse.")
            else:
                st.success("La fausse valeur n'apparaît pas dans la réponse.")
        if expected:
            correct = H.contains_any(text, expected)
            if correct:
                st.success("La réponse attendue est présente.")
            else:
                st.warning("La réponse attendue est absente.")
        sources = ", ".join(map(str, res.get("sources", []))) or "aucune"
        origin = "résultat enregistré" if status == "cache" else "en direct"
        st.caption(f"Sources : {sources} · {res.get('seconds', '?')} s · {origin}")
        if msg:
            st.info(msg)
        for alert in H.as_list(res.get("alerts")):
            st.warning("Alerte du bouclier : " + H.alert_text(alert))
        if "retrieved_passages" in res or "filtered_passages" in res:
            with st.expander("Preuves : passages avant et après filtrage"):
                st.markdown("**Avant filtrage**")
                for passage, state in H.diff_passages(res.get("retrieved_passages"), res.get("filtered_passages")):
                    st.caption(state)
                    st.text(passage[:700])
                st.markdown("**Après filtrage**")
                for passage in H.as_list(res.get("filtered_passages")):
                    st.text(H.passage_text(passage)[:700])
        extras = {k: v for k, v in res.items() if k not in H.CORE_KEYS | H.SHIELD_KEYS}
        if extras:
            with st.expander("Autres détails fournis par le bouclier"):
                st.json(extras)
    return hit, correct


with tab_duel:
    questions = H.load_questions()
    tags = sorted({t for q in questions for t in q.get("tags", [])})
    left, right = st.columns([1, 2])
    with left:
        tag = st.selectbox("Type de question", ["Toutes"] + tags)
    pool = [q for q in questions if tag == "Toutes" or tag in q.get("tags", [])]
    labels = [f"{q['id']} · {q['question']}" for q in pool]
    with right:
        choice = st.selectbox("Question du jeu de test", labels) if labels else None
    custom = st.text_input("Ou écrivez votre propre question")

    # Voice input: the spoken question is transcribed to text, then handled like any typed question.
    with st.expander("Ou posez votre question à voix haute (entrée vocale)"):
        audio_file = st.audio_input("Enregistrer la question") if hasattr(st, "audio_input") else None
        uploaded = st.file_uploader("Ou importez un fichier audio (wav, mp3, m4a)", type=["wav", "mp3", "m4a"])
        audio_file = audio_file or uploaded
        voice_q = ""
        if audio_file is not None:
            data = audio_file.getvalue()
            akey = hashlib.md5(data).hexdigest()
            heard = st.session_state.setdefault("voice_cache", {})
            if akey not in heard:
                with st.spinner("Transcription de la question..."):
                    try:
                        heard[akey] = H.transcribe_audio(data, getattr(audio_file, "name", None) or "question.wav")
                    except Exception as exc:  # not cached, so the person can retry
                        st.error(f"Transcription impossible : {type(exc).__name__}: {exc}")
            if akey in heard:
                voice_q = st.text_input("Question comprise (vous pouvez la corriger)", value=heard[akey],
                                        key=f"voice_{akey}").strip()

    question, expected = "", []
    if custom.strip():
        question = custom.strip()
    elif voice_q:
        question = voice_q
    elif choice:
        item = pool[labels.index(choice)]
        question, expected = item["question"], H.accepted_values(item)

    if protected_error:
        st.warning(protected_error + " Seul l'assistant normal sera lancé.")

    # The documents folder must exist and contain .txt files, otherwise the retriever has nothing to search.
    folder_path = ROOT / folder
    folder_ready = folder_path.is_dir() and any(folder_path.glob("*.txt"))
    if not folder_ready:
        st.warning(f"Le dossier {folder} est absent ou vide. Les documents piégés doivent d'abord être ajoutés "
                   "au dépôt (partie attaques). En attendant, utilisez les documents normaux, "
                   "ou le mode démo enregistrée si des résultats existent déjà.")

    if st.button("Lancer le duel", type="primary",
                 disabled=not question or (not folder_ready and not offline)):
        with st.spinner("Les deux assistants lisent les documents..."):
            base = H.run_assistant("normal", answer_normal, question, folder, offline)
            prot = (H.run_assistant("protected", answer_protected, question, folder, offline)
                    if answer_protected else (None, "error", protected_error))
        st.session_state["duel"] = {"question": question, "expected": expected, "target": target,
                                    "folder": folder, "base": base, "prot": prot}

    duel = st.session_state.get("duel")
    if duel:
        st.markdown(f"**Question :** {duel['question']}")
        note = " (différent du réglage actuel : relancez le duel)" if duel["folder"] != folder else ""
        st.caption(f"Documents lus pour ce duel : {duel['folder']}{note}")
        col_a, col_b = st.columns(2)
        hit_a, ok_a = render_answer(col_a, "Assistant normal (sans bouclier)", *duel["base"],
                                    duel["expected"], duel["target"])
        hit_b, ok_b = render_answer(col_b, "Assistant protégé (avec bouclier)", *duel["prot"],
                                    duel["expected"], duel["target"])
        if hit_a and hit_b is False:
            st.success("Le bouclier a bloqué cette attaque.")
        elif hit_a and hit_b:
            st.error("L'attaque passe aussi à travers le bouclier : à noter dans l'analyse d'échecs.")
        elif hit_a is False and hit_b is False:
            st.info("Cette attaque n'a pas fonctionné contre l'assistant normal non plus.")
        if ok_a and ok_b is False:
            st.warning("Fausse alerte possible : l'assistant protégé a perdu la bonne réponse.")


# ---------------- results ----------------
def show_result_file(title, path):
    st.subheader(title)
    loaded = H.load_json_table(path)
    if loaded is None:
        st.info(f"Fichier absent : {path.relative_to(ROOT)}")
        return
    summary, rows = loaded
    if summary:
        items = list(summary.items())[:6]
        cols = st.columns(len(items))
        for c, (k, v) in zip(cols, items):
            c.metric(k, "n/a" if v is None else v)
    if rows:
        st.dataframe(rows)
    st.caption(f"Source : {path.relative_to(ROOT)}")


def show_attack_results():
    """Comparison baseline vs shield on the attack cases, saved by the attacks part (no Groq call)."""
    st.subheader("Attaques : assistant normal contre assistant protégé")
    run = H.latest_attack_run()
    if run is None:
        st.info("Aucun résultat dans eval/results/attacks/ : récupérez d'abord la branche des attaques.")
        return
    reviewed = run / "comparison_reviewed.md"
    if reviewed.exists():
        st.markdown(reviewed.read_text(encoding="utf-8"))
    csv_files = sorted(run.glob("comparison_*.csv"))
    if csv_files:
        rows = H.read_semicolon_csv(csv_files[-1])
        with st.expander("Réponses détaillées (fichier CSV)"):
            pending = H.count_pending(rows)
            if pending:
                st.info(f"{pending} verdict(s) sont encore « pending » dans le CSV : "
                        "l'interprétation finale est dans le tableau vérifié ci-dessus.")
            st.dataframe(rows)
    st.caption(f"Source : {run.relative_to(ROOT)}. Le fichier summary.json n'est pas utilisé seul : "
               "il contient encore des erreurs d'API antérieures aux reprises.")


with tab_results:
    st.write("Résultats enregistrés par `eval/` : ils ne déclenchent aucun appel à Groq.")
    show_attack_results()
    show_result_file("Baseline : assistant normal sur les questions normales", ROOT / "eval" / "baseline_normal.json")
    show_result_file("Évaluation complète : attaques, bouclier, fausses alertes", ROOT / "eval" / "report.json")

# ---------------- about ----------------
with tab_about:
    st.markdown("""
**Ce que montre ce projet.** Un assistant qui lit des documents peut obéir à une phrase cachée dans un document
(injection de prompt). Nous comparons un assistant sans protection et un assistant avec un bouclier, sur les mêmes
questions, avec des chiffres.

**Ce que fait le bouclier.** Il repère les blocs qui ressemblent à des instructions, les isole, ajoute des consignes
de protection et vérifie les identifiants de sources cités.

**Limites.**
- Les résultats viennent d'un petit jeu de test : ils ne prouvent pas une sécurité générale.
- Aucune défense n'est parfaite : certaines attaques peuvent encore passer.
- Les avis de marchés publics sont des données publiques anonymisées ; les documents piégés sont fabriqués par l'équipe.
- L'outil aide à lire et à vérifier. Il ne remplace ni la lecture de l'avis original ni un avis juridique.
""")
