# ModLearn Lab

Web platform of the ModLearn Technology Lab at the University College of
Teacher Education Vorarlberg (Pädagogische Hochschule Vorarlberg, Austria).
School classes get stepwise help with mathematics tasks from a language
model that runs on the school's own hardware; teachers run the sessions and
can read every dialogue. The user interface is German.

What the software does:

- **Task help (mathematics).** A child types, photographs or dictates a
  task. The tutor first asks where the difficulty lies, then gives help in
  graded steps (motivation, feedback, general strategy, content strategy,
  solution), following Zech's taxonomy of minimal help. Every help text
  passes deterministic output checks (no solution before the last step, no
  invented quotes, no narrowing "fill in a number" questions). The teacher
  sets how far the help may go.
- **Teacher's task pool.** During a lesson the teacher can put tasks into
  the session (text or photo). Each task is solved once by the local model
  and, if the teacher enabled quality assurance, by an external model; the
  teacher sees whether the two agree before the class works on it.
- **Quality assurance (optional, per session).** A frontier model may
  check the local model's solution. Only the task text goes out, rewritten
  without persons, with named entities masked, after a leak check, under a
  budget guard. Photos go out only as a masked and cropped print region,
  and only if the teacher allowed images for that session.
- **Other lesson types.** A vocabulary trainer, an English speaking coach
  (speech recognition on the model host, optionally a server voice that
  reads the coach's turns sentence by sentence), a music lesson and a
  moderated safe chat.
- **Lesson boundary.** Before a model answers, the server asks a
  gatekeeper one question only: does this contribution belong to the
  lesson? The gatekeeper is the local model with its own instruction, or
  a second model if configured; it judges relevance, never sensitivity,
  because a topic list would be a censorship list. If the answer is no,
  the application itself replies with a fixed sentence that leads back to
  the task, in the lesson's language; no model writes that reply. This
  holds for the trainer, both help paths of the mathematics tutor and the
  speaking coach (`tutoring/fachgrenze.py`).
- **Which AI works here.** A public page (`/ki/`) names the models in
  use with maker and country, explains the lesson boundary and shows the
  numbers of the neutrality probe. In the safe chat every answer carries
  the name of the model that wrote it, and an answer that has the form of
  a political refusal never reaches the child verbatim; the child reads
  that the local model evaded and can ask the teacher or, if the teacher
  allowed it, send the question through the filter to the external model.
- **Neutrality probe.** `benchmark/neutralitaet/` asks twelve question
  pairs, each a question a Chinese model might balk at next to an equally
  delicate comparison question, at four places in the application, and
  counts twice: the form of each answer automatically, and the content of
  every free answer as judged by a second model with written criteria and
  a note per answer. Run N1 (Qwen3.6-35B-A3B, 96 answers) is included
  with all answers and all judgements; the numbers feed the `/ki/` page.
- **Teacher views.** Class overview with one tile per child, the full
  dialogue of every child including what went to the external model and
  what came back, an estimate of the child's own share of the work, and
  the child's rating of the help.
- **Research protocol.** Pseudonymous per-request log (route, model,
  tokens, duration, leak check) with configurable detail level.
- **Booking.** A small booking system for sessions on the shared model
  host (`plan/`).

## Architecture

```
Phone / browser ──HTTPS──> web server
                            Django 5.2, PostgreSQL 16, uvicorn
                            behind a reverse proxy with TLS (we use Caddy)
                                 │
                                 │ private network (we use a Tailscale/WireGuard
                                 │ overlay; any private link works)
                                 ▼
                            model host
                            vLLM, OpenAI-compatible API, text + vision
                            optional: Whisper (speech), model broker, music service
                                 │
                                 ▼ (optional, teacher-enabled, masked text only)
                            external frontier API (OpenAI-compatible)
```

The web server is the only machine that children and teachers talk to. The
model host is never exposed to the internet; the application reaches it
through a private network. The model host can be any DGX Spark-class
device; ours is an ASUS Ascent GX10 (NVIDIA GB10 Grace Blackwell, 128 GB
unified memory) running vLLM with Qwen3.6-35B-A3B, and the model selection
is tuned to that class of machine. Nothing in the code depends on it: the
endpoint is configuration.

The full picture, with diagrams of the two machines, the privacy wall, the
logging levels and what teachers and learners see, is in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

### The model endpoint is interchangeable

`SPARK_BASE_URL` and `SPARK_MODEL` point to any OpenAI-compatible chat
endpoint (vLLM, llama.cpp server, Ollama, a hosted API). Photographed tasks
need a model that accepts images in chat messages (`image_url` with a data
URL); with a text-only model, typed and dictated tasks still work.

Optional services, each switched off when its address is empty:

| Setting | Service | Interface |
|---|---|---|
| `SPARK_AUDIO_BASE_URL` | speech recognition for the speaking coach | OpenAI-compatible `/audio/transcriptions` (we run whisper-large-v3) |
| `SPARK_BROKER_URL` | model broker: which models are loaded on the host | small HTTP service, see `plan/broker.py` |
| `MUSIK_URL` | music generation for the music lesson | small HTTP service, see `core/musik.py` |
| `PFOERTNER_BASE_URL`, `PFOERTNER_MODEL` | gatekeeper for the lesson boundary on a second model | OpenAI-compatible chat; empty means the main model judges with its own instruction |
| `SPARK_TTS_BASE_URL` | server voice for the speaking coach | OpenAI-compatible `/audio/speech` (we run Qwen3-TTS-1.7B); empty falls back to the browser voice |
| `CLOUD_BASE_URL`, `CLOUD_MODEL`, `CLOUD_API_KEY` | external quality assurance | OpenAI-compatible chat; without a key the switch is a dry run |

The services on the model host (vLLM compose files, broker, music service)
are not part of this repository.

## Running it

Requirements: Docker with Compose, or Python 3.12 with PostgreSQL.

```sh
cp .env.example .env        # fill in secret key, database password, teacher password, model endpoint
docker compose up --build   # app on http://127.0.0.1:8090 (APP_PORT), behind your own TLS proxy
```

On start the container waits for the database, applies migrations and
creates or updates the teacher account from `TEACHER_USERNAME` and
`TEACHER_PASSWORD`. Secrets for the reverse-proxy login and the broker are
read from files under `/run/geheim` (mounted from `GEHEIM_VERZEICHNIS`);
the external API key belongs in `../.env.cloud` next to the project, never
in the repository.

Development without Docker:

```sh
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
DJANGO_SECRET_KEY=x python -m pytest --ds=config.settings_test   # SQLite in memory
DJANGO_SECRET_KEY=x python manage.py runserver --settings=config.settings_test
```

`config/settings_test.py` swaps PostgreSQL for an in-memory SQLite database
and drops the static-files manifest; everything else is the production
configuration.

## Repository layout

| Path | Content |
|---|---|
| `core/` | start page, project page, legal pages, login through the institution's proxy, music lesson |
| `tutoring/` | sessions, participants, tasks, help levels (`levels.py`), diagnosis (`pruefung.py`), output checks (`ausgabepruefung.py`), model client (`spark.py`), external quality assurance with masking (`cloud.py`), image chain (`bildkette.py`), teacher's task pool (`aufgabenpool.py`), lesson boundary (`fachgrenze.py`), server voice (`stimme.py`), teacher views, research protocol |
| `plan/` | booking of sessions on the model host, model broker client |
| `benchmark/mathe/` | benchmark of the help pipeline: 60 own tasks (`aufgaben.json`), 12 simulated children (`profile.json`), runner, evaluation, all results (`ergebnisse/`), development log (`ENTWICKLUNG.md`) |
| `benchmark/bildkette/` | measurement of the image chain on generated notebook pages (no photos of children) |
| `benchmark/bildnutzen/` | measurement of what forwarding a masked image adds to quality assurance; the official test items (iKMPLUS, Matura) used there are not included, only their identifiers and the numbers in the README |
| `benchmark/neutralitaet/` | neutrality probe: question pairs, runner with re-evaluation (`--auswerten`), all answers of run N1 (`ergebnisse/`) and the judgements with criteria (`urteile/`) |
| `docs/` | `ARCHITECTURE.md` (English: the two machines, the privacy wall, logging, what teachers and learners see), design documents in German (didactics in the prompt, help after diagnosis, image forwarding, privacy classification, the benchmark report) and `neutralitaet/ergebnis.json`, the numbers shown on `/ki/` |
| `static/`, `templates/` | own graphics, styles, scripts, page templates |

## Privacy design in short

- No accounts for children. A session is a six-digit code; a child picks an
  animal as its name for the lesson. Sessions expire and are deleted.
- Nothing leaves the web server except requests to the model host on the
  private network.
- The external path exists only for quality assurance, only when the
  teacher switches it on for a session, and only with the task text:
  rewritten without persons, entities masked, leak-checked, counted against
  a budget. The child's own attempt never goes out. Teachers see every
  outbound and inbound text in the dialogue view.
- Images go out only through the image chain: re-encoded without metadata,
  located by the vision model, handwriting, names, faces and logos masked,
  cropped to the printed task, fail-closed on any doubt.
- The research protocol stores pseudonymous keys per session and
  participant; the detail level (counts only, masked texts, original
  texts) is a server setting documented in `docs/Datenschutz_Einordnung.md`.
- The political leaning of the local model is measured, not assumed, and
  disclosed on `/ki/` together with the model's maker and country. Off-topic
  questions never reach a model during a lesson; the server answers them.

## Citation

See `CITATION.cff`. Source: https://github.com/harubert/modlearn-lab. Once
the repository is archived on Zenodo, the DOI will be listed here and in
`CITATION.cff`.

## Licence

European Union Public Licence v. 1.2 (EUPL-1.2), see `LICENSE`.

The didactic rules in `tutoring/levels.py` and the documents in `docs/`
build on Friedrich Zech, *Grundkurs Mathematikdidaktik*; quotations are
marked as such. The logos of the Pädagogische Hochschule Vorarlberg and of
the European Union in `static/img/` are the property of their owners and
are not covered by the licence.

## Acknowledgements

ModLearn Technology Lab, Pädagogische Hochschule Vorarlberg, within the
Erasmus project "GenAI-Natives".
