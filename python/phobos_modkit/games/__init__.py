"""Game adapters: public file-format knowledge for one game each, in our own words."""


def publish_adapters():
    """{Steam app ID: Adapter} for every game whose mods the Workshop publishing tools can read."""
    from .ostranauts.publish import Ostranauts
    from .rimworld.publish import RimWorld
    return {adapter.app_id: adapter for adapter in (RimWorld(), Ostranauts())}
