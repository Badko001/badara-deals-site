"""Selector map structure. All selectors live in this package - nowhere else."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.browser.raw import PageKind


@dataclass(frozen=True)
class SelectorSet:
    """Primary selector first, then fallbacks, tried in order."""

    candidates: tuple[str, ...]
    required: bool = False

    def __post_init__(self) -> None:
        if not self.candidates:
            raise ValueError("A SelectorSet needs at least one candidate")


def sel(*candidates: str, required: bool = False) -> SelectorSet:
    return SelectorSet(tuple(candidates), required=required)


@dataclass(frozen=True)
class SelectorMap:
    name: str
    #: True only once every selector was checked against the real page
    #: (e.g. with ``playwright codegen`` during a real, manually logged-in session).
    verified: bool
    #: Allowed hostnames: data read elsewhere is never "confirmed by the airline".
    official_hosts: tuple[str, ...]
    page_markers: dict[PageKind, SelectorSet]
    logged_in_marker: SelectorSet
    booking_link: SelectorSet
    #: Scalar fields, keyed by ``RawPageObservation`` attribute name.
    fields: dict[str, SelectorSet]
    passenger_row: SelectorSet
    passenger_fields: dict[str, SelectorSet]
    offer_row: SelectorSet
    offer_id_attribute: str
    offer_fields: dict[str, SelectorSet]
    offer_accept_button: SelectorSet
    messages: SelectorSet
    confirmation_total: SelectorSet
    confirmation_miles: SelectorSet
    payment_form_marker: SelectorSet
    final_confirm_button: SelectorSet
    #: Elements masked on any debug screenshot (names, references, tickets...).
    pii_mask: tuple[str, ...] = field(default_factory=tuple)
