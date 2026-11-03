"""Vérification locale du contrôle de dates ; aucun import du pipeline."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    path = ROOT / 'app/output_checks.py'
    spec = importlib.util.spec_from_file_location('shieldloop_output_dates', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    validate = module.validate_output
    count = 0

    def check(label, condition):
        nonlocal count
        if not condition:
            raise AssertionError(label)
        count += 1
        print('OK :', label)

    question = 'Quelle est la date limite de réponse ?'
    sources = [{
        'id': 'ao_01.txt',
        'text': (
            'dateparution: 2015-03-03\n'
            'datelimitereponse: 2015-04-20T11:00:00+00:00\n'
            'gestion.INDEXATION.DATE_LIMITE_REPONSE: 2015-04-20T12:00:00+01:00\n'
        ),
    }]
    for answer in [
        '20 avril 2015 [ao_01.txt]',
        '20\u202favril\u202f2015 [ao_01.txt]',
        '20/04/2015 [ao_01.txt]',
        '2015-04-20 [ao_01.txt]',
        '20-04-2015 [ao_01.txt]',
    ]:
        check('Date équivalente acceptée : '+answer, not validate(question,answer,sources)['output_blocked'])

    for label, answer in [
        ('Fausse date bloquée', '30 avril 2015 [ao_01.txt]'),
        ('Date présente mais mauvais champ bloquée', '3 mars 2015 [ao_01.txt]'),
        ('Citation absente bloquée sur une date', '20 avril 2015'),
        ('Citation inconnue bloquée', '20 avril 2015 [inconnu.txt]'),
        ('Date impossible bloquée', '31 février 2015 [ao_01.txt]'),
        ('Date relative non interprétée bloquée', 'Demain [ao_01.txt]'),
    ]:
        result=validate(question,answer,sources)
        check(label,result['output_blocked'])
        check('Réponse brute conservée',result['raw_answer']==answer)

    extra = sources + [{'id':'other.txt','text':'datelimitereponse: 2015-04-30'}]
    check('Date dans une autre source non citée refusée',validate(question,'30 avril 2015 [ao_01.txt]',extra)['output_blocked'])
    check('Source sans champ échéance : blocage explicite',validate(question,'20 avril 2015 [ao_01.txt]',[{'id':'ao_01.txt','text':'Date évoquée : 20 avril 2015'}])['output_blocked'])
    check('NOT FOUND reste identifiable',validate(question,'NOT FOUND',sources)['output_check']['status']=='not_found')
    check('Question sans date non concernée',validate('Quel département ?', '31 [ao_01.txt]',sources)['output_check']['status']=='not_applicable')

    # Limites intentionnellement exposées, pas cachées par des assertions favorables.
    mixed=validate(question,'Le 30 avril est faux ; la date est le 20 avril 2015. [ao_01.txt]',sources)
    print('NOTE : seules les dates complètes avec année sont extraites ; les relations sémantiques ne sont pas vérifiées.')
    quote=validate(question,'Pas le 30 avril 2015 ; le 20 avril 2015. [ao_01.txt]',sources)
    print('LIMITE : une fausse date citée pour être réfutée provoque un blocage conservateur =',quote['output_blocked'])
    print(f'\n{count} contrôles réussis. Aucun appel API. Aucun fichier modifié.')
    print('Le contrôle porte sur les dates, pas sur tous les nombres ni tous les faits.')


if __name__ == '__main__':
    main()
