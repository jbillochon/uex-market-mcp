# -*- coding: utf-8 -*-
"""Normalisation, filtrage et classement des annonces UEX.

Fonctions pures sur des dictionnaires : aucune base, aucun reseau. Le meme
code sert au bot Discord (sur sa base locale) et au skill autonome (sur la
reponse directe de l API).
"""
from __future__ import annotations

import time

from .quality import effective_quality

LISTING_URL = "https://uexcorp.space/marketplace/item/info/%s/"
DAY = 86400

SORTS = ("quality", "recent", "price")
OPERATIONS = ("sell", "buy")


def listing_url(slug):
    return LISTING_URL % slug if slug else None


def _num(valeur):
    try:
        return float(valeur)
    except (TypeError, ValueError):
        return None


def normalize(raw, systems=None):
    """Annonce brute de l API vers une ligne plate, qualite resolue.

    `systems` est un dict facultatif id_star_system -> nom.
    """
    q = effective_quality(raw.get("quality"), raw.get("title") or "",
                          raw.get("description") or "")
    prix = _num(raw.get("price"))
    systeme = None
    if systems and raw.get("id_star_system"):
        systeme = systems.get(raw.get("id_star_system"))
    return dict(
        id=int(raw.get("id")),
        id_item=int(raw.get("id_item") or 0),
        id_category=int(raw.get("id_category") or 0),
        operation=raw.get("operation") or "",
        type=raw.get("type") or "",
        slug=raw.get("slug") or "",
        url=listing_url(raw.get("slug")),
        title=(raw.get("title") or "").strip(),
        price=prix if prix and prix > 0 else None,
        unit=(raw.get("unit") or "").lower() or None,
        currency=raw.get("currency") or "UEC",
        location=(raw.get("location") or "").strip() or None,
        id_star_system=int(raw.get("id_star_system") or 0),
        system=systeme,
        source=raw.get("source") or None,
        availability=raw.get("availability") or None,
        language=raw.get("language") or None,
        in_stock=int(raw.get("in_stock") or 0),
        is_sold_out=int(raw.get("is_sold_out") or 0),
        seller=raw.get("user_username") or "",
        seller_name=raw.get("user_name") or "",
        votes=int(raw.get("votes") or 0),
        q_declared=raw.get("quality"),
        q_eff=q["q_eff"],
        q_min=q["q_min"],
        q_max=q["q_max"],
        q_source=q["source"],
        q_multi=1 if q["multi"] else 0,
        date_added=int(raw.get("date_added") or 0),
        date_expiration=int(raw.get("date_expiration") or 0),
    )


def is_active(row, now=None):
    now = now or time.time()
    if row.get("is_sold_out"):
        return False
    exp = row.get("date_expiration") or 0
    return not exp or exp > now


def search(rows, operation="sell", quality_min=None, quality_max=None,
           max_age_days=None, price_max=None, system=None, location=None,
           seller=None, include_unknown=True, sort="quality",
           dedupe_seller=True, limit=10, now=None):
    """Filtre et classe. Rend (resultats, stats).

    Regles :
    - seules les annonces actives comptent (ni epuisees, ni expirees) ;
    - le filtre de qualite porte sur la PLAGE de l annonce : une annonce
      "517, 681, 747" passe un seuil de 700 ;
    - une annonce de qualite inconnue ne passe jamais un seuil de qualite,
      et sans seuil elle est classee apres toutes les qualites connues ;
    - a qualite egale, la plus recente d abord ;
    - une seule annonce par vendeur, la mieux classee, sinon un vendeur
      prolifique occupe tout le classement.
    """
    now = now or time.time()
    stats = dict(total=0, active=0, matched=0, sellers=0, dropped_dupes=0)
    candidats = []
    for r in rows:
        stats["total"] += 1
        if operation and r.get("operation") != operation:
            continue
        if not is_active(r, now):
            continue
        stats["active"] += 1
        if max_age_days and now - (r.get("date_added") or 0) > max_age_days * DAY:
            continue
        if quality_min is not None:
            if r.get("q_max") is None or r["q_max"] < quality_min:
                continue
        if quality_max is not None:
            if r.get("q_min") is None or r["q_min"] > quality_max:
                continue
        if quality_min is None and quality_max is None and not include_unknown:
            if r.get("q_eff") is None:
                continue
        if price_max is not None and r.get("price") and r["price"] > price_max:
            continue
        if system:
            if (r.get("system") or "").lower() != system.lower():
                continue
        if location:
            if location.lower() not in (r.get("location") or "").lower():
                continue
        if seller:
            if seller.lower() not in (r.get("seller") or "").lower():
                continue
        candidats.append(r)
    stats["matched"] = len(candidats)

    def q_cle(r):
        # Qualite d affichage, ramenee dans la fenetre demandee : pour une
        # annonce multi-qualites filtree a 700+, c est sa meilleure qualite
        # qui compte, pas la premiere declaree.
        q = r.get("q_max") if r.get("q_multi") else r.get("q_eff")
        return q if q is not None else -1

    if sort == "recent":
        cle = lambda r: (-(r.get("date_added") or 0), -q_cle(r))
    elif sort == "price":
        cle = lambda r: (r.get("price") is None, r.get("price") or 0,
                         -q_cle(r))
    else:
        cle = lambda r: (-q_cle(r), -(r.get("date_added") or 0))
    candidats.sort(key=cle)

    if dedupe_seller:
        vus, uniques = set(), []
        for r in candidats:
            qui = (r.get("seller") or "").lower()
            if qui and qui in vus:
                stats["dropped_dupes"] += 1
                continue
            vus.add(qui)
            uniques.append(r)
        candidats = uniques
    stats["sellers"] = len(set((r.get("seller") or "").lower() for r in candidats))
    return candidats[:limit] if limit else candidats, stats


def display_quality(row):
    """Libelle court : '974', '~886' si deduite, '517-747' si plage,
    '500?' si valeur par defaut non confirmee, '?' si inconnue."""
    if row.get("q_eff") is None:
        return "?"
    if row.get("q_multi") and row.get("q_min") != row.get("q_max"):
        return "%d-%d" % (row["q_min"], row["q_max"])
    if row.get("q_source") == "default":
        return "%d?" % row["q_eff"]
    if row.get("q_source") in ("title", "description"):
        return "~%d" % row["q_eff"]
    return "%d" % row["q_eff"]


def age_days(row, now=None):
    now = now or time.time()
    return max(0, int((now - (row.get("date_added") or now)) // DAY))
