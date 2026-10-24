"""Calcul des périodes (mois/année) et interpolation des masques de la config."""

from datetime import date

MOIS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
           "août", "septembre", "octobre", "novembre", "décembre"]


def periodes(piece, aujourdhui=None):
    """Liste des (année, mois) à récupérer, du plus récent au plus ancien.

    - decalage_mois : nombre de mois à remonter avant le premier (1 = mois précédent,
      utile car la fiche de paie du mois en cours n'est souvent pas encore émise) ;
    - nombre_mois : nombre de mois consécutifs à récupérer (3 pour les bulletins).
    """
    aujourdhui = aujourdhui or date.today()
    decalage = int(piece.get("decalage_mois", 0))
    nombre = int(piece.get("nombre_mois", 1))
    index = aujourdhui.year * 12 + aujourdhui.month - 1 - decalage
    return [divmod(index - i, 12) for i in range(nombre)]


def variables(periode):
    year, mois0 = periode
    return {"year": year, "month": mois0 + 1, "mois_nom": MOIS_FR[mois0]}


def formater(masque, periode):
    """Applique str.format (syntaxe f-string : {month:02d}, {year}, {mois_nom}).

    Les accolades propres aux regex doivent être doublées : \\d{{2}}.
    """
    return masque.format(**variables(periode))
