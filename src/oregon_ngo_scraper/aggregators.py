"""Hosts that are never an organization's own homepage.

The resolver and the crawler both need this judgement, and they used to keep
separate lists that drifted apart: a directory site absent from the resolver's
list would be selected as an org's homepage, and then — because it was also
absent from the crawler's list — crawled, so the *directory's* phone and email
ended up recorded as the organization's.

Keeping one list here means adding a host fixes both call sites at once.

Three kinds of host are listed:

* **Social networks.** Real, but not a homepage.
* **Charity data brokers.** IRS-derived profile pages (ProPublica, GuideStar,
  501c3lookup, …). These rank highly for small rural nonprofits that have no
  website of their own, which is exactly our population.
* **Service directories.** Shelter/clinic/housing finders that republish an
  org's listing. Empirically the worst offenders for this dataset, because
  their pages carry a plausible-looking address and phone that belong to the
  directory or to a different provider entirely.
"""

from __future__ import annotations

from urllib.parse import urlparse


SOCIAL_HOSTS: tuple[str, ...] = (
    "facebook.com",
    "twitter.com",
    "x.com",
    "instagram.com",
    "linkedin.com",
    "youtube.com",
    "yelp.com",
    "nextdoor.com",
    "tiktok.com",
)

CHARITY_DATA_HOSTS: tuple[str, ...] = (
    "propublica.org",
    "guidestar.org",
    "candid.org",
    "charitynavigator.org",
    "charityindex.org",
    "501c3lookup.org",
    "causeiq.com",
    "greatnonprofits.org",
    "nonprofitlist.org",
    "nonprofitlocator.org",
    "nonprofitscan.com",
    "searchcharities.org",
    "plaincharity.com",
    "charityscoop.info",
    "taxexemptworld.com",
    "f990.org",
    "irs.gov",
    "opencorporates.com",
)

SERVICE_DIRECTORY_HOSTS: tuple[str, ...] = (
    "shelterlistings.org",
    "freeclinicdirectory.org",
    "affordablehousingonline.com",
    "apartmentsmart.com",
    "providerresourceswa.org",
    "needhelppayingbills.com",
    "homelessshelterdirectory.org",
    "rentassistance.us",
    "findhelp.org",
    "auntbertha.com",
    "idealist.org",
    "intellispect.co",
    "healthshareoregon.org",
)

#: Sites that list our target organizations but are not those organizations.
OTHER_NOISE_HOSTS: tuple[str, ...] = (
    "wikipedia.org",
    "google.com",
    "bing.com",
    "duckduckgo.com",
    "amazonaws.com",
    "ocadsv.org",  # the coalition that lists member DSV programs
)

#: Every host fragment the resolver and crawler should refuse.
NOISE_HOST_FRAGMENTS: tuple[str, ...] = (
    SOCIAL_HOSTS + CHARITY_DATA_HOSTS + SERVICE_DIRECTORY_HOSTS + OTHER_NOISE_HOSTS
)


def is_noise_host(host_or_url: str) -> bool:
    """True when ``host_or_url`` belongs to a social/aggregator/directory site.

    Accepts either a bare host or a full URL, since the resolver works with
    parsed hosts and the crawler with URLs.
    """
    value = (host_or_url or "").strip().lower()
    if not value:
        return False
    if "://" in value:
        value = urlparse(value).netloc.lower()
    return any(fragment in value for fragment in NOISE_HOST_FRAGMENTS)
