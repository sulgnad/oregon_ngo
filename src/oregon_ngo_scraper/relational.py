"""Column layout for the workbook's ``Organization`` and ``Location`` tables.

Where :mod:`.snmp` targets the flat ``Map Database`` sheet, this module targets
the normalized side of the same workbook: the ``Organization Table`` and
``(Main) Location Table`` sheets, whose fields are specified in the
``Codebook`` sheet.

Only these two tables are produced. ``Service`` and ``Service_at_Location``
are left alone for now.

Column names are copied verbatim from the sheet headers, including their
misspellings (``organziation_description``, ``location_adress``). They are
reproduced rather than corrected so the output can be pasted straight into
the existing sheets; fixing them here would silently misalign the columns.

The sheets key rows as ``ORG_001`` / ``LOC_001``. Per your decision these
carry derived GUIDs instead — see :mod:`.ids` for why.
"""

from __future__ import annotations

from .ids import location_id, organization_id
from .models import Organization
from .snmp import DEFAULT_LANGUAGES, services_summary


#: ``Organization Table`` header, verbatim. Note that ``organization_name`` is
#: spelled correctly while the four fields after it are not.
ORGANIZATION_COLUMNS: tuple[str, ...] = (
    "organization_id",
    "organization_name",
    "organziation_description",
    "organziation_email",
    "organziation_website",
    "organziation_phone",
)

#: ``(Main) Location Table`` header, verbatim.
LOCATION_COLUMNS: tuple[str, ...] = (
    "location_id",
    "organization_id",
    "location_type",
    "location_name",
    "location_description",
    "location_hours",
    "location_hours_notes",
    "location_adress",
    "location_website",
    "location_phone",
    "location_transportation",
    "location_languages",
    "location_accessibility",
    "location_status",
)

#: Location fields no public web source reliably provides. Emitted empty so a
#: human can fill them in without the column layout shifting, matching how
#: :data:`.snmp.MANUAL_COLUMNS` is handled on the flat sheet.
#:
#: ``location_transportation`` is in here deliberately: the Codebook asks
#: whether it can be scraped, and the answer is no — transit links are not
#: published in any consistent place on these sites.
MANUAL_LOCATION_COLUMNS: frozenset[str] = frozenset(
    {
        "location_hours",
        "location_hours_notes",
        "location_transportation",
        "location_accessibility",
    }
)

#: Allowed values are ``Physical/Virtual/Postal``. Every row in this dataset is
#: ``Physical``: the county scoping rule only admits organizations with a
#: physical office in Jefferson or Tillamook, so a virtual or postal-only
#: presence would have been filtered out before reaching this point.
DEFAULT_LOCATION_TYPE = "Physical"

#: Allowed values are ``Active/Incative`` (sic). Rows are written only for
#: organizations whose sites responded during collection.
DEFAULT_LOCATION_STATUS = "Active"


def to_organization_row(org: Organization) -> dict[str, str]:
    """Map an :class:`Organization` onto the ``Organization Table`` columns."""
    return {
        "organization_id": organization_id(org),
        "organization_name": org.name or "",
        "organziation_description": services_summary(org),
        "organziation_email": org.email or "",
        "organziation_website": org.website or "",
        "organziation_phone": org.phone or "",
    }


def to_location_row(org: Organization) -> dict[str, str]:
    """Map an :class:`Organization`'s primary location onto the location columns.

    The pipeline models one organization as one place, so this emits a single
    location row per organization. The schema supports more, and because
    ``location_id`` is derived from the address (see :func:`.ids.location_key`)
    additional locations can be added later without disturbing existing keys.

    ``location_description`` repeats the organization's summary. For a
    single-location organization the two genuinely describe the same thing,
    and the flat sheet sets the precedent by storing identical text in
    ``Services_Summary`` and ``Org_Agency_Bio``.
    """
    row = {column: "" for column in LOCATION_COLUMNS}
    row.update(
        {
            "location_id": location_id(org),
            "organization_id": organization_id(org),
            "location_type": DEFAULT_LOCATION_TYPE,
            "location_name": org.name or "",
            "location_description": services_summary(org),
            "location_adress": org.address or "",
            "location_website": org.website or "",
            "location_phone": org.phone or "",
            "location_languages": DEFAULT_LANGUAGES,
            "location_status": DEFAULT_LOCATION_STATUS,
        }
    )
    return row
