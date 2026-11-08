"""Publishing mods to the Steam Workshop from a repository: release notes from changelogs, offline staging, the
owner-run uploader, pulling Steam's live state back, and worksheets for tidying change notes.

Everything here but the uploader is offline or reads Steam's public, keyless API. The uploader (upload.py) is run by
the owner only, in their own console: it hands the login to SteamCMD's own prompt and never sees a password. Agents,
tests and continuous integration never run a real upload.
"""
