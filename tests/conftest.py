import pathlib
import sys

RACINE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))                  # paquet `agent`
sys.path.insert(0, str(RACINE / "mcp_server"))   # modules `serveur`, `outils_calcul`
