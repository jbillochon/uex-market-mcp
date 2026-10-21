# -*- coding: utf-8 -*-
"""Qualite effective d une annonce de la marketplace UEX.

Le champ `quality` saisi par le vendeur est absent, nul ou laisse a la
valeur par defaut dans environ 15 % des annonces de minerais, alors que la
qualite figure souvent dans le titre ("Dolivine 886Q", "Q965", "550-676q").
Inversement, un vendeur qui propose plusieurs qualites dans une annonce
("Stileron q517, q681, q747") ne peut en declarer qu une seule.

On rend donc, pour chaque annonce :
  q_eff     la qualite a afficher et a trier (declaree si credible, sinon
            deduite du titre, sinon de la description, sinon None) ;
  q_min / q_max  la plage de toutes les qualites connues de l annonce, qui
            sert au filtrage : une annonce "517, 681, 747" doit sortir pour
            une recherche "700 et plus" ;
  source    'declared', 'title', 'description', 'default' ou 'none' ;
  multi     vrai quand l annonce porte plusieurs qualites distinctes.

Aucune dependance hors bibliotheque standard : ce module est exporte tel
quel dans le skill autonome.
"""
from __future__ import annotations

import re

QMIN = 1
QMAX = 1000
DEFAULT_QUALITY = 500

# Plages explicites : "550-676q", "Q526-916", "[554-959Q]", "q500-700".
_RANGE = re.compile(
    r"(?<![\d.,])q?\s*(\d{3,4})\s*(?:-|to|a)\s*q?\s*(\d{3,4})\s*q?(?![\d.,%])",
    re.IGNORECASE)
# Qualite marquee : "886Q", "Q965", "q 517", "1000 Q", "quality 1000",
# "qual. 900", "qlt 950". La lettre Q ne doit pas etre le debut d un mot
# (Quantainium, Quartz) ni la fin d un mot (Ouratite... ne finit pas par
# q, mais "Iraq" si) : on exige une frontiere de mot.
_MARKED = re.compile(
    r"(?:"
    r"\b(?:q|ql|qlt|qual|quality|qualite|calidad)\.?\s*[:#]?\s*(\d{1,4})(?![\d.]|,\d)"
    r"|"
    r"(?<![\d.,])(\d{1,4})\s*(?:q|ql|qlt|qual|quality)\b"
    r")",
    re.IGNORECASE)
# Nombre nu de 3 ou 4 chiffres. Accepte seulement s il n est pas un prix,
# un volume, une quantite ou une date : pas de decimale ni de separateur
# accole, pas d unite derriere, pas de "x" devant, et pas membre d un nombre
# a milliers separes par des espaces ("400 000"). Dans le doute on
# s abstient : une qualite absente classe l annonce en "inconnue", une
# qualite fausse tromperait le joueur.
_BARE = re.compile(r"(?<![\d.,$x#])(?<!\d\s)(\d{3,4})(?![\d.,%])(?!\s\d{3}\b)(?!\s*(?:k\b|m\b|mil|million|"
                   r"scu|cscu|uscu|auec|uec|units?\b|u\b|x\b|pcs|ea\b|each|%|p\b|"
                   r"gems?|rocks?|boxes|crates?))",
                   re.IGNORECASE)
# Mots qui annoncent un nombre qui n est pas une qualite. "for" n y est
# pas : "looking for 947 or 972" parle bien de qualites.
_NOT_QUALITY_BEFORE = re.compile(
    r"(?:\bx|\bqty\s*:|\bstock\s*:?|\bprice\s*:?|\blot of|\bpack of|\$)\s*$",
    re.IGNORECASE)


def _valide(valeur, plancher=QMIN):
    try:
        v = int(valeur)
    except (TypeError, ValueError):
        return None
    return v if plancher <= v <= QMAX else None


def qualities_in_text(texte, bare=True):
    """Toutes les qualites lisibles dans un texte, sans doublon, triees.

    `bare` autorise les nombres nus de 3 a 4 chiffres (100 a 1000). On le
    coupe pour la description, pleine de statistiques et de prix.
    """
    if not texte:
        return []
    trouve = set()
    reste = texte
    for m in _RANGE.finditer(texte):
        a, b = _valide(m.group(1), 100), _valide(m.group(2), 100)
        if a and b and a < b:
            trouve.update((a, b))
            reste = reste.replace(m.group(0), " ")
    for m in _MARKED.finditer(reste):
        # Plancher a 100 : "Q50" ou "50 qty" sont des quantites, et aucune
        # annonce relevee ne vend un minerai sous 100 de qualite.
        v = _valide(m.group(1) or m.group(2), 100)
        if v:
            trouve.add(v)
    if bare:
        sans_marques = _MARKED.sub(" ", reste)
        for m in _BARE.finditer(sans_marques):
            avant = sans_marques[:m.start()]
            if _NOT_QUALITY_BEFORE.search(avant):
                continue
            v = _valide(m.group(1), 100)
            if v:
                trouve.add(v)
    return sorted(trouve)


def effective_quality(declared, title="", description=""):
    """Rend un dict q_eff, q_min, q_max, source, multi."""
    dec = _valide(declared, 2)
    du_titre = qualities_in_text(title, bare=True)
    de_desc = [] if du_titre else qualities_in_text(description, bare=False)
    texte = du_titre or de_desc

    if dec is not None and dec != DEFAULT_QUALITY:
        source, q_eff = "declared", dec
    elif dec == DEFAULT_QUALITY and not texte:
        # 500 est la valeur proposee par defaut : credible pour un minerai
        # mais impossible a distinguer d un champ non rempli.
        source, q_eff = "default", dec
    elif texte:
        source = "title" if du_titre else "description"
        q_eff = max(texte)
    else:
        source, q_eff = "none", None

    connues = set(texte)
    if q_eff is not None:
        connues.add(q_eff)
    if not connues:
        return dict(q_eff=None, q_min=None, q_max=None, source=source,
                    multi=False)
    return dict(q_eff=q_eff, q_min=min(connues), q_max=max(connues),
                source=source, multi=len(connues) > 1)
