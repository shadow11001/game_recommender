# Game Recommender Engine

A personal game recommendation system that aggregates your game libraries from multiple platforms (Steam, PlayStation, Xbox, Epic, GOG) and provides recommendations based on your play history and preferences using IGDB metadata.

## Features

- **Multi-Platform Integration**: Consolidates games from Steam, PSN, Xbox, Epic Games, and GOG.
- **Smart Recommendations**: Uses content-based filtering to recommend games from your backlog or new discoveries.
- **Data Visualization**: Visualize your library statistics and playtime.
- **Web Interface**: Clean Flask-based UI to browse, search, and manage your collection.

## Prerequisites

- **Python 3.11+**
- **IGDB API Crednetials** (Client ID & Secret) from [Twitch Developers](https://dev.twitch.tv/).
- **Steam API Key** from [Steam Community](https://steamcommunity.com/dev/apikey).
- **PSN NPSSO Token** (for PlayStation support).
- **Xbox Authentication Tokens** (json file).
- **GOG Authentication Token** (txt file).

## Configuration

You can configure most services directly through the Web Interface by clicking the **Integrations** button.

Alternatively, you can manually set up the environment:

1.  **Environment Variables**:
    Copy `.env.example` to `.env` and fill in your API keys (optional if using UI):
    ```bash
    cp .env.example .env
    ```
    *   `STEAM_API_KEY`, `STEAM_ID`
    *   `PSN_NPSSO`
    *   `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET`

2.  **Platform Tokens**:
    *   **Xbox**: Requires `xbox_tokens.json` in the root directory. This contains your OAuth2 tokens. Uploading via UI is supported.
    *   **GOG**: Requires `gog_token.txt` in the root directory. Paste cookie/JSON via UI.
    *   **Epic Games**: Requires `~/.config/legendary` (Legendary-GL config) to be present on the host (and mounted/copied if using specific setups).

## Running Manually

1.  **Create a Virtual Environment**:
    ```bash
    python -m venv .venv
    source .venv/bin/activate  # On Windows: .venv\Scripts\activate
    ```

2.  **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

3.  **Ingest Data**:
    Run the ingestion script to fetch games from connected platforms and populate the local database (`data/games.db`).
    ```bash
    export PYTHONPATH=$PYTHONPATH:$(pwd)/src
    python src/ingest.py
    ```

4.  **Start the Web Server**:
    ```bash
    export PYTHONPATH=$PYTHONPATH:$(pwd)/src
    python src/web.py
    ```
    Access the application at `http://localhost:5001`.

## Running with Docker

1.  **Build and Start**:
    ```bash
    docker compose up -d --build
    ```
    This starts the container and automatically launches the web application.
    Access the application at `http://localhost:5001`.

2.  **Ingest Data**:
    You can trigger ingestion from the Web UI (look for a Sync button), or run it manually via the CLI:
    ```bash
    docker compose exec app python src/ingest.py
    ```
    *Note: For Epic Games support in Docker, you may need to mount your local `~/.config/legendary` folder to `/root/.config/legendary` in `docker-compose.yml`.*

## Project Structure

- `src/`: Source code.
  - `ingest.py`: Scripts for fetching data from APIs.
  - `web.py`: Flask web application.
  - `recommend.py`: Recommendation engine logic.
  - `templates/`: HTML templates.
- `data/`: SQLite databases.
- `scripts/`: various debug and maintenance scripts.
