"""Interface Streamlit : on voit le raisonnement du LLM et chaque outil MCP.

L'UI ne contient AUCUNE logique métier : elle envoie la question à l'API de
l'agent (POST /calcul) et met en scène la trace renvoyée — pensées du modèle,
appels d'outils MCP, refus de l'arbitre, réponse finale validée.
"""

import json
import os

import httpx
import streamlit as st

AGENT_URL = os.environ.get("AGENT_URL", "http://localhost:8080")

st.set_page_config(page_title="Calculatrice agent ReAct", page_icon="🧮",
                   layout="centered")

EXEMPLES = [
    "trois fois quatre plus deux",
    "dix moins deux fois trois",
    "ouvre parenthèse deux plus trois ferme parenthèse fois quatre",
    "cent divisé par quatre divisé par cinq",
]


# ---------------------------------------------------------------------------
# Barre latérale : état du service + exemples
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("⚙️ Service")
    try:
        sante = httpx.get(f"{AGENT_URL}/sante", timeout=5).json()
        st.success(f"Agent en ligne — modèle `{sante.get('modele', '?')}`")
    except Exception:
        st.error(f"Agent injoignable ({AGENT_URL})")
    st.header("💡 Exemples")
    for exemple in EXEMPLES:
        if st.button(exemple, use_container_width=True):
            st.session_state["question"] = exemple
    st.caption(
        "L'agent ne calcule jamais lui-même : chaque opération passe par les "
        "outils MCP, et un arbitre rejette toute réponse non construite par "
        "les outils."
    )


# ---------------------------------------------------------------------------
# Mise en scène d'une étape de la trace ReAct
# ---------------------------------------------------------------------------

def afficher_etape(etape: dict) -> None:
    if etape["type"] == "pensee":
        with st.expander("💭 Raisonnement du modèle", expanded=False):
            st.markdown(etape["contenu"])
    elif etape["type"] == "outil":
        with st.expander(f"🔧 Outil MCP : `{etape['nom']}`", expanded=True):
            colonne_args, colonne_resultat = st.columns(2)
            with colonne_args:
                st.caption("Arguments")
                st.json(etape["arguments"])
            with colonne_resultat:
                st.caption("Résultat")
                resultat = etape["resultat"]
                if isinstance(resultat, (dict, list)):
                    st.json(resultat)
                else:
                    st.code(json.dumps(resultat, ensure_ascii=False),
                            language="json")
    elif etape["type"] == "refus_arbitre":
        proposition = etape.get("reponse_proposee")
        if proposition:
            st.error(f"⛔ **Arbitre** — {etape['detail']}\n\n"
                     f"*Réponse proposée par le modèle :* `{proposition}`")
        else:
            st.error(f"⛔ **Arbitre** — {etape['detail']}\n\n"
                     f"*Appel refusé :* `{etape.get('nom')}"
                     f"({json.dumps(etape.get('arguments', {}), ensure_ascii=False)})`")
    elif etape["type"] == "erreur_outil":
        st.warning(f"⚠️ Erreur de l'outil `{etape.get('nom')}` : {etape['detail']}")


# ---------------------------------------------------------------------------
# Corps de la page
# ---------------------------------------------------------------------------

st.title("🧮 Calculatrice agent ReAct")
st.markdown(
    "Posez un calcul **en français** : le petit LLM local raisonne en boucle "
    "*Penser → Agir → Observer* et n'a le droit de calculer **qu'avec les "
    "outils MCP**."
)

question = st.text_input(
    "Votre question",
    value=st.session_state.get("question", EXEMPLES[0]),
    key="champ_question",
)

if st.button("Calculer", type="primary"):
    with st.chat_message("user"):
        st.write(question)

    with st.spinner("Le LLM réfléchit (inférence CPU locale, patience)…"):
        try:
            reponse_http = httpx.post(f"{AGENT_URL}/calcul",
                                      json={"question": question},
                                      timeout=600)
            reponse_http.raise_for_status()
            donnees = reponse_http.json()
        except Exception as erreur:
            st.error(f"Appel de l'agent impossible : {erreur}")
            st.stop()

    with st.chat_message("assistant"):
        for etape in donnees["etapes"]:
            afficher_etape(etape)

        if donnees["valide"]:
            reponse = donnees["reponse"]
            if float(reponse).is_integer():
                reponse = int(reponse)
            st.success(
                f"### ✅ {donnees['formule']} = {reponse}\n"
                f"{donnees['iterations']} itérations — réponse construite par "
                f"les outils et validée par l'arbitre."
            )
        else:
            st.error(f"### ❌ Échec — {donnees.get('erreur', 'raison inconnue')}")
