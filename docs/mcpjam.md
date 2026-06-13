# Tutoriel — MCPJam, l'inspecteur MCP

[MCPJam](https://github.com/mcpjam/inspector) est un **inspecteur** pour serveurs
MCP : une interface web qui se connecte à un serveur MCP, liste ses outils, et
permet de les **appeler à la main** — sans écrire une ligne de code et sans LLM.
C'est l'outil idéal pour comprendre, déboguer et tester un serveur MCP avant (ou
pendant) le développement de l'agent.

Dans ce projet, MCPJam tourne comme un service Docker (`mcpjam`) sur le port
**6274**.

## 1. Pourquoi un inspecteur

Quand on développe un serveur MCP, on veut répondre vite à des questions comme :

- mes outils sont-ils bien exposés, avec le bon schéma ?
- que renvoie `calculer(3, "*", 4)` exactement ?
- mes messages d'erreur (division par zéro, mot non reconnu) sont-ils clairs ?
- le serveur respecte-t-il bien le protocole (découverte, appels) ?

Sans inspecteur, il faudrait écrire un client à chaque fois. MCPJam donne une UI
qui parle le protocole MCP à votre place.

## 2. Ouvrir MCPJam

La stack étant démarrée (`docker compose up -d`), ouvrez :

```
http://localhost:6274
```

Note : la documentation Docker de MCPJam mentionne parfois le port 4000, mais la
version 2.x (utilisée ici, 2.0.5) écoute sur **6274**. C'est le port publié dans
[`docker-compose.yml`](../docker-compose.yml).

## 3. Connecter le serveur MCP de la calculatrice

Dans MCPJam, ajoutez un serveur avec ces paramètres :

- **Type de transport** : HTTP (parfois nommé « Streamable HTTP » ou
  « HTTP / SSE » selon les versions).
- **URL** :
  ```
  http://mcp-server:8000/mcp/
  ```

Pourquoi ce nom d'hôte et pas `localhost` ? Parce que la connexion au serveur
MCP est établie **côté conteneur MCPJam** (un proxy interne), pas depuis votre
navigateur. Or le conteneur MCPJam et le conteneur `mcp-server` sont sur le même
réseau Docker : MCPJam résout `mcp-server` directement. (Vérifié : depuis le
conteneur, `http://mcp-server:8000/sante` répond bien.)

Si une version de MCPJam établissait la connexion côté navigateur, utilisez
alors l'URL publiée sur l'hôte : `http://localhost:8000/mcp/`.

Une fois connecté, MCPJam affiche le statut du serveur et la liste de ses outils.

## 4. Lister et appeler les outils

Vous devriez voir les 4 outils : `convertir_texte_en_formule`,
`trouver_calcul_prioritaire`, `calculer`, `remplacer_calcul_par_resultat`.
Cliquez sur l'un d'eux : MCPJam génère un formulaire à partir du **schéma**
(les paramètres typés). Exemples à essayer :

| Outil | Arguments | Résultat attendu |
|---|---|---|
| `convertir_texte_en_formule` | `texte = "trois fois quatre plus deux"` | `"3 * 4 + 2"` |
| `trouver_calcul_prioritaire` | `formule = "3 * 4 + 2"` | un objet indiquant `3 * 4` |
| `calculer` | `gauche = 3, operateur = "*", droite = 4` | `12` |
| `remplacer_calcul_par_resultat` | `formule = "3 * 4 + 2", sous_expression = "3 * 4", valeur = 12` | `"12 + 2"` |

Vous reproduisez ainsi, à la main, exactement ce que l'agent fait en boucle.

## 5. Tester l'anti-triche sans LLM

C'est l'exercice le plus instructif. Les garde-fous sont **dans les outils**,
donc ils s'appliquent même quand c'est vous (et non un LLM) qui appelez :

- Appelez `remplacer_calcul_par_resultat` avec une **valeur fausse** :
  `formule = "3 * 4 + 2", sous_expression = "3 * 4", valeur = 99`.
  -> L'outil **refuse** : 99 n'est pas le résultat de `3 * 4`.
- Appelez-le avec une sous-expression **non prioritaire** :
  `formule = "3 * 4 + 2", sous_expression = "4 + 2", valeur = 6`.
  -> L'outil **refuse** : `4 + 2` n'est pas le calcul prioritaire.
- Provoquez une erreur métier : `calculer` avec `gauche = 1, operateur = "/",
  droite = 0`.
  -> Message clair « Division par zero impossible » (une `ToolError`, pas une
  stack trace).

Cela montre concrètement que l'impossibilité de tricher ne dépend pas du LLM :
elle est garantie par le serveur MCP lui-même.

## 6. Dépannage

- **La page ne s'ouvre pas** : vérifiez que le conteneur tourne
  (`docker compose ps`), et utilisez bien le port **6274**.
- **« Connection failed » à la connexion** : vérifiez l'URL
  (`http://mcp-server:8000/mcp/`, avec le slash final) et que `mcp-server` est
  *healthy*. Test rapide depuis l'hôte : `curl http://localhost:8000/sante`.
- **Aucun outil listé** : le serveur a peut-être redémarré ; reconnectez le
  serveur dans MCPJam.

## 7. Aller plus loin

MCPJam fonctionne avec **n'importe quel** serveur MCP, pas seulement celui-ci.
Quand vous écrirez d'autres serveurs MCP (ou des serveurs qui en orchestrent
d'autres), c'est votre premier réflexe de test : connectez, listez, appelez,
vérifiez les schémas et les erreurs — puis seulement, branchez l'agent.

## À retenir

- MCPJam = inspecteur web pour appeler les outils MCP à la main, sans LLM.
- Ici : `http://localhost:6274`, connexion au serveur via
  `http://mcp-server:8000/mcp/`.
- Idéal pour vérifier schémas, résultats et messages d'erreur — et pour
  constater que l'anti-triche est dans les outils, pas dans le modèle.
