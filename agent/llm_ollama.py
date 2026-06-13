"""Client minimal pour l'API de chat d'Ollama (avec appel d'outils).

L'interface est volontairement réduite à une seule méthode `repondre`, ce qui
permet de remplacer le vrai LLM par un faux LLM scripté dans les tests.
"""

import httpx


class LLMOllama:
    def __init__(self, url: str, modele: str):
        self.url = url.rstrip("/")
        self.modele = modele

    async def repondre(self, messages: list, outils: list) -> dict:
        """Envoie la conversation + les outils, renvoie le message du modèle.

        Le message renvoyé contient soit `tool_calls` (le modèle veut agir),
        soit `content` (le modèle veut répondre).
        """
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as http:
            reponse = await http.post(
                f"{self.url}/api/chat",
                json={
                    "model": self.modele,
                    "messages": messages,
                    "tools": outils,
                    "stream": False,
                    # température 0 : sorties aussi déterministes que possible ;
                    # num_predict : un appel d'outil tient en ~50 tokens (plus
                    # l'éventuel raisonnement « thinking »), on coupe court si
                    # le petit modèle part en boucle de génération
                    "options": {"temperature": 0, "num_ctx": 4096,
                                "num_predict": 512},
                    # garde le modèle chargé en mémoire entre deux appels
                    "keep_alive": "30m",
                },
            )
            reponse.raise_for_status()
            return reponse.json()["message"]
