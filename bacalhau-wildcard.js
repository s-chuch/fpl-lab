// Manually captured from Bacalhau's public "Pick Team" screen — the app has
// no API for a rival's PROVISIONAL squad before their deadline (only the
// locked squad afterward, via the normal picks endpoint), so this is a
// hand-updated snapshot, not something refresh.py can compute. Update this
// file (and "captured_at") whenever a newer screenshot comes in; Bacalhau
// can still change this squad right up to the deadline below.
window.FPL_WILDCARD_WATCH = {
  "team": "Bacalhau",
  "gw": 6,
  "deadline": "2026-10-10 06:00 ET",
  "status": "provisional",
  "captured_at": "2026-09-20",
  "chips": {
    "bboost": "unavailable",
    "3xc": "played_gw3",
    "wildcard": "active",
    "freehit": "unavailable"
  },
  "xi": [
    { "pos": "GKP", "name": "Raya", "club": "ARS", "fixture": "LEE (H)" },
    { "pos": "DEF", "name": "Gvardiol", "club": "MCI", "fixture": "LIV (A)" },
    { "pos": "DEF", "name": "Hall", "club": "NEW", "fixture": "COV (A)" },
    { "pos": "DEF", "name": "Tarkowski", "club": "EVE", "fixture": "HUL (A)", "vice": true },
    { "pos": "DEF", "name": "Bogle", "club": "LEE", "fixture": "ARS (A)" },
    { "pos": "DEF", "name": "De Cuyper", "club": "BHA", "fixture": "SUN (A)" },
    { "pos": "MID", "name": "Belloumi", "club": "HUL", "fixture": "EVE (H)" },
    { "pos": "MID", "name": "Dewsbury-Hall", "club": "EVE", "fixture": "HUL (A)" },
    { "pos": "MID", "name": "Groß", "club": "BHA", "fixture": "SUN (A)", "captain": true },
    { "pos": "MID", "name": "Schade", "club": "BRE", "fixture": "AVL (A)" },
    { "pos": "FWD", "name": "Haaland", "club": "MCI", "fixture": "LIV (A)" }
  ],
  "bench": [
    { "pos": "GKP", "name": "Tzolakis", "club": "HUL", "fixture": "EVE (H)" },
    { "pos": "MID", "name": "Tavernier", "club": "BOU", "fixture": "CHE (A)" },
    { "pos": "FWD", "name": "Kostoulas", "club": "BHA", "fixture": "SUN (A)" },
    { "pos": "FWD", "name": "Walle Egeli", "club": "IPS", "fixture": "FUL (H)" }
  ],
  "note": "Provisional squad from Bacalhau's own Pick Team screen — this can still change before the GW6 deadline (Sat 10 Oct, 06:00). Treat as a strong signal of intent, not a locked squad."
};
