"""La boucle ReAct (Reason + Act), écrite à la main pour rester lisible.

À chaque itération :
  1. PENSER : on envoie la conversation au LLM, avec la liste des outils MCP ;
  2. AGIR   : si le LLM demande un outil, l'arbitre vérifie l'appel, puis
              l'outil est exécuté sur le serveur MCP ;
  3. OBSERVER : le résultat (ou le refus de l'arbitre) est renvoyé au LLM,
              qui s'en sert à l'itération suivante ;
  ... jusqu'à ce que le LLM réponde sans outil : l'arbitre valide alors (ou
  refuse) la réponse finale.

Le LLM ne peut pas tricher : toute réponse non issue de la réduction complète
de la formule par les outils est refusée et la boucle continue.
"""

import json
import re

from agent.arbitre import Arbitre, est_nombre

# Un prompt COURT et directif : un petit modèle (1.5b) ignore les protocoles
# longs et se met à « calculer » tout seul en texte — exactement ce qu'on
# veut interdire. Testé : la version longue échoue, celle-ci fonctionne.
PROMPT_SYSTEME = """Tu es une calculatrice sans cerveau : tu ne sais ni convertir ni calculer toi-même.
À chaque tour, appelle exactement UN outil, celui que la consigne te demande.
Tu n'as le droit d'écrire du texte qu'à la toute fin, quand la formule est réduite à un seul nombre, au format :
REPONSE FINALE: <nombre>"""


def extraire_donnees(resultat_outil):
    """Extrait la valeur utile d'un CallToolResult FastMCP (str, float, dict…)."""
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
    """Récupère un appel d'outil écrit en JSON dans le texte.

    Les petits modèles émettent parfois {"name": ..., "arguments": {...}}
    en texte au lieu du champ structuré tool_calls — c'est d'ailleurs le
    ReAct « historique », où l'action est parsée depuis la sortie du modèle.
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
    """Cherche le nombre annoncé dans « REPONSE FINALE: 14 » (avec tolérance)."""
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
    nombre = float(nombre)
    return str(int(nombre)) if nombre.is_integer() else str(nombre)


class AgentReact:
    def __init__(self, llm, client_mcp, max_iterations: int = 25,
                 guidage: bool = True):
        self.llm = llm
        self.client_mcp = client_mcp
        self.max_iterations = max_iterations
        # guidage : après chaque outil, on souffle au LLM la prochaine étape
        # du protocole. Indispensable avec un modèle de ~1.5b ; désactivable
        # (GUIDAGE=0) avec un modèle plus capable. Les indications sont
        # dérivées UNIQUEMENT des résultats d'outils : aucun calcul caché,
        # et l'arbitre vérifie de toute façon chaque appel.
        self.guidage = guidage

    async def resoudre(self, question: str) -> dict:
        async with self.client_mcp:
            # Découverte dynamique des outils : c'est tout l'intérêt de MCP,
            # l'agent n'a aucune connaissance codée en dur des outils.
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
            etapes = []

            for iteration in range(1, self.max_iterations + 1):
                message = await self.llm.repondre(messages, outils)
                # Certains modèles (gemma4, deepseek-r1…) renvoient leur
                # raisonnement dans un champ « thinking » : on le garde dans
                # la trace pour l'afficher, mais on ne le renvoie PAS dans
                # l'historique (inutile et coûteux en contexte).
                pensee = message.pop("thinking", None)
                if pensee and pensee.strip():
                    etapes.append({"type": "pensee", "contenu": pensee.strip()})
                messages.append(message)
                appels = message.get("tool_calls") or []
                if not appels:
                    appel_textuel = extraire_appel_textuel(message.get("content"))
                    if appel_textuel:
                        appels = [appel_textuel]

                if not appels:
                    # Le LLM propose une réponse finale : l'arbitre tranche.
                    contenu = message.get("content") or ""
                    valeur = extraire_nombre_final(contenu)
                    refus = arbitre.verifier_reponse_finale(valeur)
                    if refus is None:
                        return {
                            "question": question,
                            "formule": arbitre.formule_initiale,
                            "reponse": valeur,
                            "valide": True,
                            "iterations": iteration,
                            "etapes": etapes,
                        }
                    etapes.append({"type": "refus_arbitre",
                                   "reponse_proposee": contenu,
                                   "detail": refus})
                    messages.append({"role": "user",
                                     "content": f"ARBITRE : {refus}"})
                    continue

                for appel in appels:
                    nom = appel.get("function", {}).get("name", "")
                    args = appel.get("function", {}).get("arguments") or {}
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}

                    refus = await arbitre.verifier_appel(nom, args)
                    if refus is not None:
                        observation = {"erreur": refus}
                        etapes.append({"type": "refus_arbitre", "nom": nom,
                                       "arguments": args, "detail": refus})
                    else:
                        try:
                            brut = await self.client_mcp.call_tool(nom, args)
                            observation = extraire_donnees(brut)
                        except Exception as erreur:
                            observation = {"erreur": str(erreur)}
                            etapes.append({"type": "erreur_outil", "nom": nom,
                                           "arguments": args,
                                           "detail": str(erreur)})
                        else:
                            arbitre.noter_resultat(nom, args, observation)
                            etapes.append({"type": "outil", "nom": nom,
                                           "arguments": args,
                                           "resultat": observation})

                    messages.append({
                        "role": "tool",
                        "tool_name": nom,
                        "content": json.dumps(observation, ensure_ascii=False)
                        if isinstance(observation, dict)
                        else str(observation),
                    })
                    if self.guidage:
                        # Le conseil est porté par un message utilisateur
                        # séparé : un modèle 1.5b suit un ordre direct, mais
                        # recopie en texte une consigne noyée dans un résultat
                        # d'outil (testé : l'autre variante échoue).
                        conseil = self._prochaine_etape(nom, observation, arbitre)
                        if conseil:
                            messages.append({"role": "user", "content": conseil})

            return {
                "question": question,
                "formule": arbitre.formule_initiale,
                "reponse": None,
                "valide": False,
                "iterations": self.max_iterations,
                "etapes": etapes,
                "erreur": "Nombre maximal d'itérations atteint sans réponse valide.",
            }

    # -- aides ----------------------------------------------------------------

    @staticmethod
    def _prochaine_etape(nom: str, observation, arbitre: Arbitre):
        """Prochaine étape du protocole, déduite des seuls résultats d'outils."""
        if isinstance(observation, dict) and "erreur" in observation:
            return None   # le message d'erreur guide déjà le LLM
        if nom == "convertir_texte_en_formule":
            return (f"Appelle maintenant l'outil trouver_calcul_prioritaire "
                    f"avec formule = « {arbitre.formule_courante} ».")
        if nom == "trouver_calcul_prioritaire" and isinstance(observation, dict):
            if observation.get("termine"):
                return ("La formule est réduite : réponds maintenant "
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
                return ("La formule est réduite à un seul nombre : réponds "
                        "maintenant « REPONSE FINALE: <ce nombre> ».")
            return (f"Appelle maintenant l'outil trouver_calcul_prioritaire "
                    f"avec formule = « {arbitre.formule_courante} ».")
        return None

    async def _priorite_reelle(self, formule: str) -> dict:
        """Vérité terrain de l'arbitre : on demande au serveur MCP, pas au LLM."""
        brut = await self.client_mcp.call_tool("trouver_calcul_prioritaire",
                                               {"formule": formule})
        return extraire_donnees(brut)

    @staticmethod
    def _vers_format_ollama(outil) -> dict:
        """Schéma d'outil MCP -> format attendu par l'API d'Ollama."""
        return {
            "type": "function",
            "function": {
                "name": outil.name,
                "description": outil.description or "",
                "parameters": outil.inputSchema
                or {"type": "object", "properties": {}},
            },
        }
