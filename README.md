# Auction Scout

Scans auctions on auctions-storage.com for CT, NJ, and NY, extracts tenant names from auction notices, and flags names that are likely female.

## What it does
- Scrapes CT/NJ/NY auction listings.
- Opens each auction details page to collect tenant names.
- Uses OpenAI (GPT) to return YES/NO for whether a name is likely female.
- Writes hits to `output/hits.json`, `output/hits.csv`, and `output/notifications.txt`.

## Setup (Mac / Windows / Linux)
1. Install Python 3.10+ if you don’t have it: https://www.python.org/downloads/
2. Create a `.env` file with your API key (and optional states list):
   ```
   OPENAI_API_KEY=YOUR_OPENAI_API_KEY
   OPENAI_MODEL=gpt-4.1-mini
   AUCTION_STATES=CT,NJ,NY
   ```
3. Install dependencies:
   ```
   python3 -m pip install -r requirements.txt
   ```

## Run
One-time scan:
```
python3 app.py
```

Watch mode (run every hour):
```
python3 app.py --watch --interval 3600
```

## Notes
- This tool is cautious. It returns a hit only when a name is likely female.
- Avoid harassing anyone. Use responsibly and respect privacy.
