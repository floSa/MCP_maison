"""La boucle ReAct (Reason + Act), ecrite a la main pour rester lisible.

A chaque iteration :
  1. PENSER : on envoie la conversation au LLM, avec la liste des outils MCP ;
  2. AGIR   : si le LLM demande un outil, l'arbitre verifie l'appel, puis
              l'outil est execute sur le serveur MCP ;
  3. OBSERVER : le resultat (ou le refus de l'arbitre) est renvoye au LLM,
              qui s'en sert a l'iteration suivante ;
  ... jusqu'a ce que le LLM reponde sans outil : l'arbitre valide alors (ou
  refuse) la reponse finale.

Le LLM ne peut pas tricher : toute reponse non issue de la reduction complete
de la formule par les outils est refusee et la boucle continue.

ARCHITECTURE - une seule source de verite
------------------------------------------
Le coeur de la boucle est `iter_evenements`, un GENERATEUR ASYNCHRONE qui
`yield` chaque etape (pensee, appel d'outil, refus, ...) DES qu'elle se
produit, puis un evenement final « fin » qui resume le resultat.

Deux facons de le consommer, sans duplication de logique :
  - `resoudre(question)`        -> mode bloquant, renvoie le dict final
                                   complet (API /calcul, CLI, tests) ;
  - l'endpoint SSE /calcul/stream -> relaie chaque evenement en direct a
                                   l'interface Streamlit.
"""

import json
import re

from agent.arbitre import Arbitre, est_nombre

# Un prompt COURT et directif : un petit modele (1.5b) ignore les protocoles
# longs et se met a « calculer » tout seul en texte — exactement ce qu'on
# veut interdire. Teste : la version longue echoue, celle-ci fonctionne.
PROMPT_SYSTEME = """Tu es une calculatrice sans cerveau : tu ne sais ni convertir ni calculer toi-meme.
A chaque tour, appelle exactement UN outil, celui que la consigne te demande.
Tu n'as le droit d'ecrire du texte qu'a la toute fin, quand la formule est reduite a un seul nombre, au format :
REPONSE FINALE: <nombre>"""


def extraire_donnees(resultat_outil):
    """Extrait la valeur utile d'un CallToolResult FastMCP (str, float, dict...)."""
    donnees = getattr(resultat_outil, "data", None)
    if donnees is not None:
        return donnees
    for contenu in getattr(resultat_outil, "content", None) or []:
        texte = getattr(contenu, "text", None)
        if texte:
            try:
                return json.loads(texte)
            except (json.JSONDecodeError, TypeError):
                return texte
    return None


def extraire_appel_textuel(contenu: str):
    """Recupere un appel d'outil ecrit en JSON dans le texte.

    Les petits modeles emettent parfois {"name": ..., "arguments": {...}}
    en texte au lieu du champ structure tool_calls — c'est d'ailleurs le
    ReAct « historique », ou l'action est parsee depuis la sortie du modele.
    """
    if not contenu:
        return None
    texte = re.sub(r"^```(?:json)?\s*|\s*```$", "", contenu.strip())
    try:
        donnees = json.loads(texte)
    except json.JSONDecodeError:
        return None
    if (isinstance(donnees, dict) and isinstance(donnees.get("name"), str)
            and isinstance(donnees.get("arguments"), dict)):
        return {"function": {"name": donnees["name"],
                             "arguments": donnees["arguments"]}}
    return None


def extraire_nombre_final(contenu: str):
    """Cherche le nombre annonce dans « REPONSE FINALE: 14 » (avec tolerance)."""
    if not contenu:
        return None
    motif = re.search(r"REPONSE\s*FINALE\s*[:=]?\s*(-?\d+(?:[.,]\d+)?)",
                      contenu, re.IGNORECASE)
    if motif:
        return float(motif.group(1).replace(",", "."))
    nombres = re.findall(r"-?\d+(?:[.,]\d+)?", contenu)
    if nombres:
        return float(nombres[-1].replace(",", "."))
    return None


def _fmt(nombre) -> str:
    """12.0 -> '12', 2.5 -> '2.5' (pour ecrire des consignes lisibles)."""
    nombre = float(nombre)
    return str(int(nombre)) if nombre.is_integer() else str(nombre)


class AgentReact:
    """Orchestre le LLM (Ollama) et les outils MCP, sous controle de l'arbitre.

    L'agent n'a AUCUNE connaissance codee en dur des outils : il les decouvre
    a l'execution via `client_mcp.list_tools()`. C'est tout l'interet de MCP —
    pour brancher d'autres outils, il suffit de les exposer cote serveur.
    """

    def __init__(self, llm, client_mcp, max_iterations: int = 25,
                 guidage: bool = True):
        self.llm = llm
        self.client_mcp = client_mcp
        self.max_iterations = max_iterations
        # guidage : apres chaque outil, on souffle au LLM la prochaine etape
        # du protocole. Indispensable avec un modele de ~1.5b ; desactivable
        # (GUIDAGE=0) avec un modele plus capable. Les indications sont
        # derivees UNIQUEMENT des resultats d'outils : aucun calcul cache,
        # et l'arbitre verifie de toute facon chaque appel.
        self.guidage = guidage

    # -- coeur : le generateur d'evenements -----------------------------------

    async def iter_evenements(self, question: str):
        """Emet chaque etape de la boucle ReAct au fil de l'eau.

        Types d'evenements emis (chacun est un dict avec une cle « type ») :
          - {"type": "pensee", "contenu": ...}            raisonnement du modele
          - {"type": "outil", "nom", "arguments", "resultat"}   appel MCP reussi
          - {"type": "refus_arbitre", "detail", ...}      l'arbitre a bloque
          - {"type": "erreur_outil", "nom", "detail", ...}    l'outil a echoue
          - {"type": "fin", "valide", "reponse", ...}     resume final (dernier)
        """
        async with self.client_mcp:
            # Decouverte dynamique des outils exposes par le serveur MCP.
            outils = [self._vers_format_ollama(o)
                      for o in await self.client_mcp.list_tools()]
            arbitre = Arbitre(oracle_priorite=self._priorite_reelle)
            consigne = (f"Question : « {question} »\nAppelle d'abord "
                        f"convertir_texte_en_formule avec texte = « {question} »."
                        if self.guidage else question)
            messages = [
                {"role": "system", "content": PROMPT_SYSTEME},
                {"role": "user", "content": consigne},
            ]

            for iteration in range(1, self.max_iterations + 1):
                message = await self.llm.repondre(messages, outils)
                # Certains modeles (gemma4, deepseek-r1...) renvoient leur
                # raisonnement dans un champ « thinking » : on l'expose dans la
                # trace, mais on ne le renvoie PAS dans l'historique (inutile
                # et couteux en contexte).
                pensee = message.pop("thinking", None)
                if pensee and pensee.strip():
                    yield {"type": "pensee", "contenu": pensee.strip()}
                messages.append(message)

                appels = message.get("tool_calls") or []
                if not appels:
                    appel_textuel = extraire_appel_textuel(message.get("content"))
                    if appel_textuel:
                        appels = [appel_textuel]

                # -- Cas 1 : le LLM ne demande pas d'outil => reponse finale --
                if not appels:
                    contenu = message.get("content") or ""
                    valeur = extraire_nombre_final(contenu)
                    refus = arbitre.verifier_reponse_finale(valeur)
                    if refus is None:
                        yield self._evenement_fin(question, arbitre, valeur,
                                                  True, iteration)
                        return
                    # Reponse refusee : on le dit au LLM, et la boucle continue.
                    yield {"type": "refus_arbitre",
                           "reponse_proposee": contenu, "detail": refus}
                    messages.append({"role": "user",
                                     "content": f"ARBITRE : {refus}"})
                    continue

                # -- Cas 2 : le LLM demande un ou plusieurs outils ------------
                for appel in appels:
                    nom = appel.get("function", {}).get("name", "")
                    args = appel.get("function", {}).get("arguments") or {}
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}

                    # L'arbitre verifie l'appel AVANT execution.
                    refus = await arbitre.verifier_appel(nom, args)
                    if refus is not None:
                        observation = {"erreur": refus}
                        yield {"type": "refus_arbitre", "nom": nom,
                               "arguments": args, "detail": refus}
                    else:
                        try:
                            brut = await self.client_mcp.call_tool(nom, args)
                            observation = extraire_donnees(brut)
                        except Exception as erreur:  # noqa: BLE001
                            observation = {"erreur": str(erreur)}
                            yield {"type": "erreur_outil", "nom": nom,
                                   "arguments": args, "detail": str(erreur)}
                        else:
                            arbitre.noter_resultat(nom, args, observation)
                            yield {"type": "outil", "nom": nom,
                                   "arguments": args, "resultat": observation}

                    # On renvoie l'observation (resultat ou refus) au LLM.
                    messages.append({
                        "role": "tool",
                        "tool_name": nom,
                        "content": json.dumps(observation, ensure_ascii=False)
                        if isinstance(observation, dict)
                        else str(observation),
                    })
                    if self.guidage:
                        # Le conseil est porte par un message utilisateur
                        # separe : un modele 1.5b suit un ordre direct, mais
                        # recopie en texte une consigne noyee dans un resultat
                        # d'outil (teste : l'autre variante echoue).
                        conseil = self._prochaine_etape(nom, observation, arbitre)
                        if conseil:
                            messages.append({"role": "user", "content": conseil})

            # Sortie de boucle sans reponse valide.
            yield self._evenement_fin(
                question, arbitre, None, False, self.max_iterations,
                erreur="Nombre maximal d'iterations atteint sans reponse valide.")

    # -- consommateur bloquant : API /calcul, CLI, tests ----------------------

    async def resoudre(self, question: str) -> dict:
        """Deroule toute la boucle et renvoie le dict final (avec « etapes »).

        Comportement identique a l'ancienne version : on accumule simplement
        les evenements du generateur dans une liste « etapes ».
        """
        etapes = []
        final = None
        async for evenement in self.iter_evenements(question):
            if evenement["type"] == "fin":
                final = dict(evenement)
            else:
                etapes.append(evenement)
        if final is None:
            final = {"question": question, "formule": None, "reponse": None,
                     "valide": False, "iterations": 0,
                     "erreur": "Aucun evenement final emis."}
        final.pop("type", None)
        final["etapes"] = etapes
        return final

    # -- aides ----------------------------------------------------------------

    @staticmethod
    def _evenement_fin(question, arbitre, reponse, valide, iterations,
                       erreur=None):
        """Construit l'evenement « fin » (resume), avec ou sans erreur."""
        evenement = {
            "type": "fin",
            "question": question,
            "formule": arbitre.formule_initiale,
            "reponse": reponse,
            "valide": valide,
            "iterations": iterations,
        }
        if erreur is not None:
            evenement["erreur"] = erreur
        return evenement

    @staticmethod
    def _prochaine_etape(nom: str, observation, arbitre: Arbitre):
        """Prochaine etape du protocole, deduite des seuls resultats d'outils."""
        if isinstance(observation, dict) and "erreur" in observation:
            return None   # le message d'erreur guide deja le LLM
        if nom == "convertir_texte_en_formule":
            return (f"Appelle maintenant l'outil trouver_calcul_prioritaire "
                    f"avec formule = « {arbitre.formule_courante} ».")
        if nom == "trouver_calcul_prioritaire" and isinstance(observation, dict):
            if observation.get("termine"):
                return ("La formule est reduite : reponds maintenant "
                        "« REPONSE FINALE: <nombre> » avec ce nombre.")
            return (f"Appelle maintenant l'outil calculer avec "
                    f"gauche = {_fmt(observation['gauche'])}, "
                    f"operateur = \"{observation['operateur']}\", "
                    f"droite = {_fmt(observation['droite'])}.")
        if nom == "calculer" and arbitre.dernier_calcul:
            dernier = arbitre.dernier_calcul
            return (f"Appelle maintenant l'outil remplacer_calcul_par_resultat "
                    f"avec formule = « {arbitre.formule_courante} », "
                    f"sous_expression = « {dernier['sous_expression']} », "
                    f"valeur = {_fmt(dernier['resultat'])}.")
        if nom == "remplacer_calcul_par_resultat":
            if est_nombre(arbitre.formule_courante):
                return ("La formule est reduite a un seul nombre : reponds "
                        "maintenant « REPONSE FINALE: <ce nombre> ».")
            return (f"Appelle maintenant l'outil trouver_calcul_prioritaire "
                    f"avec formule = « {arbitre.formule_courante} ».")
        return None

    async def _priorite_reelle(self, formule: str) -> dict:
        """Verite terrain de l'arbitre : on demande au serveur MCP, pas au LLM."""
        brut = await self.client_mcp.call_tool("trouver_calcul_prioritaire",
                                               {"formule": formule})
        return extraire_donnees(brut)

    @staticmethod
    def _vers_format_ollama(outil) -> dict:
        """Schema d'outil MCP -> format attendu par l'API d'Ollama."""
        return {
            "type": "function",
            "function": {
                "name": outil.name,
                "description": outil.description or "",
                "parameters": outil.inputSchema
                or {"type": "object", "properties": {}},
            },
        }
