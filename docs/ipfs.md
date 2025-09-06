IPFS Integration (Scaffold)

Base Path
- Base: /ipns/libstc.cc/dois
- Purpose: Repository of weekly DOI datasets and future per-DOI content.

DOI Path Encoding
- Rule: lowercase, then encode spaces and slashes.
- Algorithm: s = doi.strip().lower(); s = s.replace(" ", "%20").replace("/", "%2F")
- Example: "10.1038/NN.12345" -> "10.1038%2Fnn.12345"

Discovery Flags
- --ipfs-fetch: Pins dataset before attempting content reads. Disabled by default.
- --store-to-db: Inserts discovered items into raw_items. Enabled by default.

Safety Notes
- pin_dataset() logs and never raises; discovery continues if IPFS is unavailable.
- try_fetch_content() is a stub in M1 and always returns None.

CLI Synopsis
- python -m pipeline discover --window-days 60 --out artifacts --ipfs-fetch=false --store-to-db=true

