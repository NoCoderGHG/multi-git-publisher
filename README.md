# Multi-Git-Publisher

GTK3/Python-Tool zum parallelen Pushen eines lokalen Git-Repos zu GitHub, GitLab und Codeberg.

## Voraussetzungen

- Python 3
- GTK3 (`python3-gi`, `gir1.2-gtk-3.0`)
- `git` im PATH

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 git
```

## Starten

```bash
python3 multi_git_publisher.py
```

## Konfiguration

Wird automatisch angelegt unter:

```
~/.config/multi-git-publisher/config.json
```

### Tokens

Tab **Tokens**: Token pro Plattform eintragen und speichern.

- GitHub: Personal Access Token (classic oder fine-grained, Scope: `repo`)
- GitLab: Personal Access Token (Scope: `write_repository`)
- Codeberg: Einstellungen → Anwendungen → Token generieren

### Repositories

Tab **Repositories**: Remote-URLs der Ziel-Repos eintragen (HTTPS).

Beispiel:
```
Name: mein-tool | Plattform: GitHub | URL: https://github.com/NoCoderGHG/mein-tool.git
Name: mein-tool | Plattform: GitLab | URL: https://gitlab.com/NoCoderGHG/mein-tool.git
Name: mein-tool | Plattform: Codeberg | URL: https://codeberg.org/NoCoderGHG/mein-tool.git
```

### Push

Tab **Veröffentlichen**:

1. Lokales Repo-Verzeichnis wählen
2. Branch eintragen (default: `main`)
3. Zielplattformen auswählen
4. **Jetzt pushen**

Der Push läuft parallel zu allen ausgewählten Plattformen, die ein konfiguriertes Repo haben.

## Hinweise

- Tokens werden **im Klartext** in `config.json` gespeichert. Dateiberechtigungen beachten (`chmod 600`).
- Der Push verwendet `git push <url> HEAD:<branch>` — kein Manipulation der lokalen Remote-Konfiguration.
- Language-Switch erfordert Neustart.

## Lizenz

MIT — NoCoderGHG
