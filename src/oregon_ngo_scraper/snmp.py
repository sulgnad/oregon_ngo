"""Column layout and controlled vocabularies for the SNMP ``Map Database``.

The target dataset is the ``Map Database`` sheet of ``SNMP_Main.xlsx``: a
flat, 28-column table. Rows produced here are meant to be appended directly
to that sheet, so both the column order and the categorical values below are
copied from what the sheet already contains rather than invented.

The workbook also carries a four-table relational schema (Organization /
Location / Service / Service_at_Location) documented in its ``Codebook``
sheet, but those tables are empty skeletons; the flat sheet is the live one.

Values were derived from the 111 populated rows. Where the sheet is
internally inconsistent — it spells the housing service three different ways
(``Housing & Shelter Assistance``, ``Shelter & Housing Assistance``,
``Housing & Shelter``) — the most frequent spelling is used.
"""

from __future__ import annotations

from .ids import location_id, organization_id
from .models import Organization, OrgType, Topic


#: Column order of the ``Map Database`` sheet. Must stay byte-identical to the
#: sheet header; ``tests/test_snmp_storage.py`` asserts this against the real
#: workbook when it is available.
SNMP_COLUMNS: tuple[str, ...] = (
    "Org_Agency_Name",
    "Org_Agency_Type",
    "Org_Agency_Level",
    "County",
    "Org_Update_Code",
    "Umbrella_Org_Agency",
    "Parent_Org_Agency",
    "Primary_Groups_Served",
    "Languages_Offered",
    "Accessibility_Features",
    "Primary_Resources_Services",
    "Services_Summary",
    "Operations_Status",
    "Primary_Location_Address",
    "Phone",
    "Email",
    "URL",
    "Parent_Org_Address",
    "Parent_Org_Phone",
    "Parent_Org_URL",
    "Days_of_Operation",
    "Hours_Schedule_Details",
    "General_Eligibility_Reqs",
    "Application_Process",
    "Free_Services",
    "Emergency_Services",
    "Org_Agency_Bio",
    "Image_URL",
)

#: Relationship keys. Absent from the flat sheet, which has no way to express
#: that one organization runs several locations; they come from the workbook's
#: relational tables, where they are the leading columns. Emitting them here
#: lets these rows be split into Organization / Location tables later without
#: re-deriving identity. See :mod:`.ids` for why they are derived GUIDs.
ID_COLUMNS: tuple[str, ...] = (
    "Organization_ID",
    "Location_ID",
)

#: What :class:`~.snmp_storage.SnmpCsvStorage` actually writes. Kept separate
#: from ``SNMP_COLUMNS`` so that tuple stays byte-identical to the sheet
#: header and the round-trip test against the real workbook keeps working.
SNMP_OUTPUT_COLUMNS: tuple[str, ...] = ID_COLUMNS + SNMP_COLUMNS

#: Columns this tool cannot populate from public web sources. They are emitted
#: empty so a human can fill them in without the column layout shifting.
MANUAL_COLUMNS: frozenset[str] = frozenset(
    {
        "Org_Update_Code",
        "Umbrella_Org_Agency",
        "Parent_Org_Agency",
        "Accessibility_Features",
        "Parent_Org_Address",
        "Parent_Org_Phone",
        "Parent_Org_URL",
        "Days_of_Operation",
        "Hours_Schedule_Details",
        "General_Eligibility_Reqs",
        "Application_Process",
        "Free_Services",
        "Emergency_Services",
        "Image_URL",
    }
)

#: The sheet only distinguishes Private (non-governmental) from Public.
ORG_TYPE_TO_AGENCY_TYPE: dict[OrgType, str] = {
    OrgType.NONPROFIT: "Private",
    OrgType.GOVERNMENT: "Public",
    OrgType.TRIBAL_GOVERNMENT: "Public",
}

#: ``Tribal`` is an addition to the sheet's observed City/County/State/Federal
#: vocabulary. Tribal governments are sovereign and none of the existing four
#: values describes them correctly.
ORG_TYPE_TO_AGENCY_LEVEL: dict[OrgType, str] = {
    OrgType.NONPROFIT: "City",
    OrgType.GOVERNMENT: "County",
    OrgType.TRIBAL_GOVERNMENT: "Tribal",
}

TOPIC_TO_SERVICE: dict[Topic, str] = {
    Topic.DSV: "Crisis Intervention & Advocacy Services",
    Topic.HOUSING: "Housing & Shelter Assistance",
    Topic.MATERNAL_HEALTH: "Medical Care",
}

TOPIC_TO_GROUP_SERVED: dict[Topic, str] = {
    Topic.DSV: "Survivors of Violence",
    Topic.HOUSING: "People Experiencing Homelessness",
    Topic.MATERNAL_HEALTH: "Pregnant/Parenting Individuals",
}

DEFAULT_GROUP_SERVED = "All Community Members"
DEFAULT_LANGUAGES = "English"
DEFAULT_OPERATIONS_STATUS = "Normal operations"

#: Deterministic ordering for multi-valued cells, so re-running the collector
#: doesn't reshuffle text and produce spurious diffs.
_TOPIC_ORDER: tuple[Topic, ...] = (Topic.DSV, Topic.HOUSING, Topic.MATERNAL_HEALTH)


def _ordered_topics(org: Organization) -> list[Topic]:
    return [t for t in _TOPIC_ORDER if t in org.topics]


def agency_type(org: Organization) -> str:
    return ORG_TYPE_TO_AGENCY_TYPE.get(org.org_type, "")


def agency_level(org: Organization) -> str:
    return ORG_TYPE_TO_AGENCY_LEVEL.get(org.org_type, "")


def county_label(org: Organization) -> str:
    """Render ``\"Jefferson\"`` as ``\"Jefferson County\"`` to match the sheet.

    Multi-county cells (``\"Deschutes / Crook / Jefferson\"``) are passed
    through untouched — the sheet already contains values of that shape, such
    as ``\"Linn/Benton/Lincoln Counties\"``.
    """
    county = (org.county or "").strip()
    if not county:
        return ""
    if "/" in county or county.lower().endswith(("county", "counties")):
        return county
    return f"{county} County"


def primary_services(org: Organization) -> str:
    return ", ".join(TOPIC_TO_SERVICE[t] for t in _ordered_topics(org))


def groups_served(org: Organization) -> str:
    groups = [TOPIC_TO_GROUP_SERVED[t] for t in _ordered_topics(org)]
    return ", ".join(groups) if groups else DEFAULT_GROUP_SERVED


def services_summary(org: Organization) -> str:
    """Prose description of what the org does.

    Falls back to the curated ``notes`` when no mission was extracted, so a
    row is rarely completely silent about the organization's purpose.
    """
    text = org.mission or org.notes or ""
    return " ".join(text.split())


def to_row(org: Organization) -> dict[str, str]:
    """Map an :class:`Organization` onto the sheet columns plus the ID keys."""
    summary = services_summary(org)
    row = {column: "" for column in SNMP_OUTPUT_COLUMNS}
    row.update(
        {
            "Organization_ID": organization_id(org),
            "Location_ID": location_id(org),
            "Org_Agency_Name": org.name or "",
            "Org_Agency_Type": agency_type(org),
            "Org_Agency_Level": agency_level(org),
            "County": county_label(org),
            "Primary_Groups_Served": groups_served(org),
            "Languages_Offered": DEFAULT_LANGUAGES,
            "Primary_Resources_Services": primary_services(org),
            "Services_Summary": summary,
            "Operations_Status": DEFAULT_OPERATIONS_STATUS,
            "Primary_Location_Address": org.address or "",
            "Phone": org.phone or "",
            "Email": org.email or "",
            "URL": org.website or "",
            # The sheet stores the same prose in both columns.
            "Org_Agency_Bio": summary,
        }
    )
    return row
