# Hearthstone Log Analyzer

Tool for parsing Hearthstone logs and extracting structured gameplay data.

## Features (current)
- Detects player ID
- Tracks turns
- Detects purchased minions (Battlegrounds)

## Planned features
- Track hand and board state
- Detect plays and sells
- Build full game state
- AI-based gameplay analysis

## How it works
The tool parses Hearthstone Power.log files using `hslog` and reconstructs gameplay events.

## Usage

1. Put your log file into the `logs/` folder
2. Run:

```bash
python main.py
