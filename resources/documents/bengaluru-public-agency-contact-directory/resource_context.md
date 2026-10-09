# Bengaluru public-agency contact directory

**What:** [Bengaluru Urban district government's directory](https://bengaluruurban.nic.in/en/directory/), with published office contacts for several agencies.

**Helps with:** Finding an agency's listed office, role, email or phone. BWSSB is the water/sewage board; BDA is the development authority; KSPCB is the pollution-control board. This is a directory, not a legal explanation of responsibilities.

**Important:** The directory still contains old BBMP offices (the former city corporation). Treat contacts as leads needing confirmation, not verified current officers or first-line complaint numbers. It does not map an address to a ward or service office. Missing fields remain marked "not listed"; no numbers have been guessed.

**Files:** `txt_source.txt` preserves page text and labelled contact rows. `fetch.py` refreshes it without saving HTML or changing this note. A recent fetch does not make old directory entries current.

From `ooru_be`:
```bash
uv run --group resources resources/documents/bengaluru-public-agency-contact-directory/fetch.py
```
