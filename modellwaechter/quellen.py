"""Die Quellen des Modellwaechters: Register, die per JSON antworten.

Kein Scraping. Hugging Face, OpenRouter, GitHub und das eigene OpenAI-Konto
haben Schnittstellen, die Listen liefern; eine Seite zu zerlegen waere
muehsamer und braeche beim naechsten Umbau. Jede Funktion bekommt den
HTTP-Client hereingereicht (Tests geben eine Attrappe) und gibt Eintraege
in derselben Form zurueck (eintrag()).

Was die Gegenstelle liefert, ist fremder Text. Jedes Feld wird auf seinen
Typ geprueft und gekuerzt, Adressen werden selbst gebaut oder auf ihren
Anfang geprueft, und nichts davon wird ausgefuehrt oder als Anweisung
gelesen. Der Schluessel des OpenAI-Kontos wandert nur in den Kopf der
Anfrage; bei Fehlern wird die ART gemeldet, nie der Text, denn httpx
schreibt in manche Meldungen die ganze Anfrage hinein.
"""

import datetime as dt

import httpx

HUGGINGFACE = "huggingface"
OPENAI = "openai"
OPENROUTER = "openrouter"
GITHUB = "github"

QUELLEN_TITEL = {
    HUGGINGFACE: "Hugging Face",
    OPENAI: "OpenAI-Konto",
    OPENROUTER: "OpenRouter",
    GITHUB: "GitHub-Releases",
}

# Wie viele Eintraege je Abfrage. Hugging Face sortiert nach letzter
# Aenderung; ein neues Repo ist immer auch frisch geaendert.
HF_ANZAHL = 100
GITHUB_ANZAHL = 10


class QuelleGescheitert(Exception):
    """Eine Quelle hat nicht geantwortet; ``art`` ist der Name des Fehlers."""

    def __init__(self, art):
        super().__init__(art)
        self.art = art


def _text(wert, laenge=200):
    return wert.strip()[:laenge] if isinstance(wert, str) else ""


def _zeit_iso(wert):
    """ISO-Zeit wie "2026-11-07T10:12:33.000Z" als Zeitpunkt mit Zone, sonst None."""
    if not isinstance(wert, str) or not wert:
        return None
    try:
        zeit = dt.datetime.fromisoformat(wert.replace("Z", "+00:00"))
    except ValueError:
        return None
    if zeit.tzinfo is None:
        zeit = zeit.replace(tzinfo=dt.timezone.utc)
    return zeit


def _zeit_unix(wert):
    if isinstance(wert, bool) or not isinstance(wert, (int, float)):
        return None
    try:
        return dt.datetime.fromtimestamp(wert, tz=dt.timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _zahl(wert):
    return wert if isinstance(wert, int) and not isinstance(wert, bool) else None


def eintrag(quelle, anbieter, kennung, *, name="", adresse="", veroeffentlicht=None,
            lizenz="", aufgabe="", merkmale=None, beschreibung=""):
    """Die eine Form, in der alle Quellen liefern."""
    return {
        "quelle": quelle,
        "anbieter": _text(anbieter, 80),
        "kennung": _text(kennung, 200),
        "name": _text(name, 200),
        "adresse": _text(adresse, 400),
        "veroeffentlicht": veroeffentlicht,
        "lizenz": _text(lizenz, 80),
        "aufgabe": _text(aufgabe, 80),
        "merkmale": merkmale or {},
        "beschreibung": _text(beschreibung, 4000),
    }


def _holen(client, adresse, headers=None):
    try:
        antwort = client.get(adresse, headers=headers or {})
        antwort.raise_for_status()
        daten = antwort.json()
    except (httpx.HTTPError, ValueError) as fehler:
        raise QuelleGescheitert(type(fehler).__name__) from fehler
    return daten


def _liste(daten, schluessel=None):
    if schluessel is not None and isinstance(daten, dict):
        daten = daten.get(schluessel)
    if not isinstance(daten, list):
        return []
    return [d for d in daten if isinstance(d, dict)]


# --- Hugging Face ------------------------------------------------------------

def huggingface(client, autor):
    """Die Modelle eines Herstellers, zuletzt geaenderte zuerst.

    Lizenz und Aufgabe stehen in den Tags ("license:apache-2.0",
    pipeline_tag). Die Groesse steht dort nicht; die holt die Einordnung
    aus der Modellkarte, wenn der Spark sie liest.
    """
    daten = _holen(
        client,
        f"https://huggingface.co/api/models?author={autor}"
        f"&sort=lastModified&direction=-1&limit={HF_ANZAHL}",
    )
    eintraege = []
    for m in _liste(daten):
        kennung = _text(m.get("id") or m.get("modelId"))
        if not kennung:
            continue
        tags = [t for t in (m.get("tags") or []) if isinstance(t, str)]
        lizenz = next((t.split(":", 1)[1] for t in tags if t.startswith("license:")), "")
        eintraege.append(eintrag(
            HUGGINGFACE, autor, kennung,
            name=kennung.split("/")[-1],
            adresse=f"https://huggingface.co/{kennung}",
            veroeffentlicht=_zeit_iso(m.get("createdAt")),
            lizenz=lizenz,
            aufgabe=m.get("pipeline_tag"),
            merkmale={
                "tags": [t[:60] for t in tags if ":" not in t][:20],
                "bibliothek": _text(m.get("library_name"), 40),
                "downloads": _zahl(m.get("downloads")),
                "likes": _zahl(m.get("likes")),
            },
        ))
    return eintraege


def modellkarte(client, kennung):
    """Die README eines Hugging-Face-Repos als Text, leer bei Fehlern.

    Der Kopf in YAML bleibt dran: Dort stehen Lizenz, Sprachen und Aufgabe
    oft genauer als im Fliesstext.
    """
    try:
        antwort = client.get(f"https://huggingface.co/{kennung}/raw/main/README.md")
        antwort.raise_for_status()
        return antwort.text if isinstance(antwort.text, str) else ""
    except (httpx.HTTPError, ValueError):
        return ""


# --- Das eigene OpenAI-Konto -------------------------------------------------

def openai_konto(client, basis, schluessel):
    """Die Modelle, die unser Konto nutzen darf: die Kandidaten fuer CLOUD_MODEL."""
    daten = _holen(
        client, f"{basis.rstrip('/')}/models",
        headers={"Authorization": f"Bearer {schluessel}"},
    )
    eintraege = []
    for m in _liste(daten, "data"):
        kennung = _text(m.get("id"))
        if not kennung:
            continue
        eintraege.append(eintrag(
            OPENAI, _text(m.get("owned_by"), 80) or "openai", kennung,
            name=kennung,
            adresse=f"https://platform.openai.com/docs/models/{kennung}",
            veroeffentlicht=_zeit_unix(m.get("created")),
        ))
    return eintraege


# --- OpenRouter --------------------------------------------------------------

def _preis_je_million(wert):
    """OpenRouter nennt Dollar je Token als Zeichenkette; hier je Million, gerundet."""
    try:
        return round(float(wert) * 1_000_000, 3)
    except (TypeError, ValueError):
        return None


def openrouter(client):
    """Alle Modelle der grossen Anbieter mit Datum, Eingaengen und Preis.

    Die Sammelquelle fuer Frontier-Modelle: Anthropic und Google haben kein
    offenes Register, hier stehen sie trotzdem, mit dem Tag des Erscheinens
    bei OpenRouter. Der Anbieter ist der Teil vor dem Schraegstrich.
    """
    daten = _holen(client, "https://openrouter.ai/api/v1/models")
    eintraege = []
    for m in _liste(daten, "data"):
        kennung = _text(m.get("id"))
        if not kennung:
            continue
        bau = m.get("architecture") if isinstance(m.get("architecture"), dict) else {}
        preise = m.get("pricing") if isinstance(m.get("pricing"), dict) else {}
        eingaenge = [e[:20] for e in (bau.get("input_modalities") or []) if isinstance(e, str)]
        eintraege.append(eintrag(
            OPENROUTER, kennung.split("/")[0], kennung,
            name=m.get("name"),
            adresse=f"https://openrouter.ai/{kennung}",
            veroeffentlicht=_zeit_unix(m.get("created")),
            aufgabe=bau.get("modality"),
            merkmale={
                "eingaenge": eingaenge[:6],
                "kontext": _zahl(m.get("context_length")),
                "usd_je_million_ein": _preis_je_million(preise.get("prompt")),
                "usd_je_million_aus": _preis_je_million(preise.get("completion")),
            },
            beschreibung=m.get("description"),
        ))
    return eintraege


# --- GitHub-Releases -----------------------------------------------------------

def github_releases(client, repo):
    """Die letzten Veroeffentlichungen eines Repos, etwa vllm-project/vllm.

    Ein neues Modell nuetzt erst, wenn vLLM es auf dem GB10 faehrt; deshalb
    gehoeren die vLLM-Versionen in dieselbe Meldung wie die Modelle.
    """
    daten = _holen(
        client, f"https://api.github.com/repos/{repo}/releases?per_page={GITHUB_ANZAHL}",
        headers={"Accept": "application/vnd.github+json"},
    )
    eintraege = []
    for r in _liste(daten):
        kennung = _text(r.get("tag_name"))
        if not kennung or r.get("draft"):
            continue
        adresse = _text(r.get("html_url"), 400)
        if not adresse.startswith("https://github.com/"):
            adresse = f"https://github.com/{repo}/releases/tag/{kennung}"
        eintraege.append(eintrag(
            GITHUB, repo, kennung,
            name=r.get("name"),
            adresse=adresse,
            veroeffentlicht=_zeit_iso(r.get("published_at")),
            merkmale={"vorab": bool(r.get("prerelease"))},
            beschreibung=r.get("body"),
        ))
    return eintraege
