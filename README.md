# agentbox

Lance des agents IA (Claude Code, GitHub Copilot CLI, ou n'importe quelle commande) dans une
sandbox **Seatbelt** macOS (`sandbox-exec`). L'agent ne voit que les dossiers **et fichiers**
listés dans `~/.config/agentbox/config.yaml`. Il n'y a pas de VM ni de dépendance externe :
Python 3 système et PyYAML suffisent.

## Installation

Prérequis : macOS et `python3` ≥ 3.9 (celui des Xcode Command Line Tools convient). Le script
installe PyYAML s'il manque.

```sh
git clone https://github.com/e-marchand/agentbox.git ~/git/agentbox
~/git/agentbox/install.sh            # lien ~/.local/bin/agentbox (--bin-dir DIR pour changer)
~/git/agentbox/install.sh --skill    # + le skill Claude Code dans ~/.claude/skills/agentbox
```

Pour mettre à jour : `git -C ~/git/agentbox pull`. Les liens pointent vers le clone, donc rien
d'autre à faire. Pour désinstaller : `~/git/agentbox/install.sh --uninstall`.

### Skill Claude Code

`skills/agentbox/SKILL.md` (en anglais) apprend à Claude à utiliser agentbox :
- côté hôte : créer et modifier des sandboxes, diagnostiquer les refus ;
- côté sandbox : `agentbox-host`, et que faire face à un `Operation not permitted`.

Pour l'installer sans cloner, utilise le plugin :

```
/plugin install agentbox --marketplace e-marchand/agentbox
```

(ou `claude plugin marketplace add e-marchand/agentbox` puis `claude plugin install agentbox@agentbox`).
Le plugin n'installe que le skill. La commande `agentbox` s'installe toujours avec `install.sh`.

## Utilisation

```sh
cd ~/git/mon-projet
agentbox init proj                       # crée la sandbox, workdir = dossier courant (rw)
agentbox add proj ~/git/lib --ro         # dossier en lecture seule
agentbox add proj ~/notes/todo.md        # un seul fichier, rw par défaut
agentbox add proj ~/git/mon-projet/.env --deny   # masqué même dans un dossier autorisé
agentbox ls proj
agentbox run proj                        # Claude Code interactif
agentbox run proj --agent copilot        # Copilot CLI
agentbox run proj -d -- -p "fix the failing tests"   # en arrière-plan, sortie dans un log
agentbox ps                              # sessions actives
agentbox stop proj                       # tue la session et tous ses processus (ou: id, pid, --all)
agentbox shell proj                      # zsh sandboxé pour tester les règles à la main
agentbox profile proj                    # affiche le profil Seatbelt généré
agentbox edit                            # édite le YAML dans $EDITOR (validé avant d'être enregistré)
```

Tout ce qui suit `--` est passé tel quel à l'agent. Voir `examples/config.yaml` pour le format
complet (variables `env`, agents personnalisés, `protect`).

## Commandes hôte (`host_commands`)

Certaines tâches ne peuvent pas tourner dans la sandbox, par exemple un build `xcodebuild` qui doit
lire tout un dépôt. Une sandbox peut donc déclarer des commandes que l'agent a le droit de faire
exécuter **hors sandbox** :

```yaml
    host_commands:
      build:
        cmd: [~/git/bigrepo/tools/build.sh]
        args: true            # l'agent peut passer des arguments (le script doit les valider)
        description: "..."
      diff:
        cmd: [git, -C, ~/git/bigrepo, diff, --, src/thefile.cpp]
```

Pendant la session, un relais non sandboxé écoute sur un socket unix
(`/private/tmp/agentbox-<uid>-<session>/`). L'agent l'utilise à travers `agentbox-host`, qui est
dans son `PATH` :

```sh
agentbox-host list                 # commandes autorisées
agentbox-host run build -c Debug   # exécute et affiche la sortie ; le code de retour est celui de la commande
agentbox-host start build          # en arrière-plan, puis: agentbox-host wait build / status / kill
```

Règles de sécurité :
- Seules les commandes listées peuvent être lancées, et sans argument tant que `args: true` n'est
  pas mis.
- agentbox **refuse de démarrer** si le programme d'une commande hôte est modifiable depuis la
  sandbox. Sinon, l'agent pourrait réécrire ce qui s'exécute dehors.
- Si le client est interrompu, la commande continue (on s'y rattache avec `wait`). Elle est tuée
  quand la session de l'agent se termine.

## Arguments propres à une sandbox (`agent_args`)

```yaml
    agent_args:
      claude: [--add-dir, ~/git/autre, --append-system-prompt, "Tu es dans une sandbox..."]
```

Ces arguments sont ajoutés à la commande de l'agent nommé. Ils ne s'appliquent ni aux autres
agents ni à `agentbox shell`.

## Ce que voit l'agent

| | lecture | écriture |
|---|---|---|
| `/Users/*` (tout `$HOME`) et `/Volumes` | non | non |
| chemins `ro` / `rw` de la config | oui | `rw` seulement |
| chemins `deny` | non | non |

Les règles s'appliquent dans l'ordre de la liste et la dernière l'emporte. Un `ro` ou un `deny`
placé dans un dossier `rw`, plus bas dans la liste, restreint donc ce sous-chemin.
| état de l'agent (`~/.claude`, `~/.claude.json`, `~/.copilot`…) | oui | oui |
| `~/.gitconfig`, `~/.config/git` | oui | non |
| système (`/usr`, `/opt/homebrew`, `/Applications`…) | oui | non |
| `/tmp`, `$TMPDIR`, `/dev` | oui | oui |
| réseau | ouvert | |

Les processus enfants (git, npm, bash lancé par l'agent…) héritent de la sandbox.

Dans `$HOME`, `stat()` reste autorisé partout pour que la résolution des chemins fonctionne.
L'agent peut donc tester si un chemin existe, mais il ne peut ni lister un dossier ni lire un contenu.

Un **fichier seul** en `rw` autorise aussi ses fichiers temporaires frères (`f.tmp.123`, `f~`,
`.f.swp`). Les écritures atomiques « écrire puis renommer » fonctionnent ainsi. Créer tout autre
fichier dans le même dossier reste interdit.

## Protections anti-évasion

Certains fichiers sont relus par l'agent quand **tu** le lances plus tard hors sandbox. Leur
écriture est toujours refusée : `~/.claude/settings*.json`, `~/.claude/CLAUDE.md`,
`~/.claude/{hooks,agents,commands,skills,plugins,output-styles}` et
`~/.copilot/{mcp-config.json,agents,skills,hooks}`. Pour les autoriser, mets `protect: false`
dans la sandbox.

Ce n'est **pas** couvert, à toi d'ajouter des `deny` si tu ne veux pas prendre le risque :
- `~/.claude.json` doit rester en écriture pour que Claude fonctionne, or il contient aussi les
  serveurs MCP de scope utilisateur.
- Dans un dépôt `rw` : `.git/hooks`, `.git/config` (`core.fsmonitor`, `core.hooksPath`),
  `.claude/settings.json`, `.vscode/tasks.json`… Ces fichiers peuvent exécuter du code quand tu
  utilises git ou un éditeur hors sandbox.
  Exemple : `agentbox add proj ~/git/mon-projet/.git/hooks ~/git/mon-projet/.git/config --ro`.
  Avec `ro`, git peut encore lire ces fichiers (`status`, `log` et `commit` fonctionnent), mais
  l'agent ne peut pas les modifier. Avec `deny`, git ne pourrait plus lire sa config.

## Limites connues

- **Pas de sandbox imbriquée** : `sandbox-exec` refuse de s'appliquer dans un processus déjà
  sandboxé. agentbox lance donc Claude avec `--settings '{"sandbox":{"enabled":false}}'`.
- **Les binaires setuid sont refusés** (`ps`, `sudo`, `top`…). C'est voulu par Seatbelt.
- **Les permissions de Claude Code restent actives** : Claude refuse lui-même les chemins hors
  de son répertoire de travail. Si tu fais confiance à la sandbox, ajoute
  `--dangerously-skip-permissions` (voir `examples/config.yaml`) ou `--add-dir` pour les autres
  dossiers autorisés.
- **Isolation plus faible qu'une VM** : même noyau, même utilisateur, réseau ouvert. L'agent
  hérite aussi des variables d'environnement du terminal, tokens compris.
- `~/Library/Keychains` est lisible, pour l'authentification par trousseau. Les éléments du
  trousseau restent protégés par leurs ACL.
- `sandbox-exec` est marqué déprécié par Apple, mais il reste utilisé par Claude Code, Chrome, etc.
- `agentbox add/rm/edit` réécrivent le YAML : les commentaires sont perdus avec `add`/`rm`.
- Les modules Python de l'utilisateur (`~/Library/Python`) sont masqués. C'est pour ça que le
  client `agentbox-host` n'utilise que la bibliothèque standard.
- Pour trouver ce qui manque à un outil, observe les refus pendant qu'il tourne :
  `/usr/bin/log stream --style compact --predicate 'sender == "Sandbox"'`
  (dans zsh, `log` tout court est une fonction intégrée).

## Variables d'environnement

- `AGENTBOX_CONFIG` : chemin du YAML (défaut `~/.config/agentbox/config.yaml`)
- `AGENTBOX_STATE` : sessions et logs (défaut `~/.local/state/agentbox`)
- `AGENTBOX=<nom>` est défini **dans** la sandbox
