"""Renders a MOCK AIR FRANCE HTML page from a raw scenario.

Used to exercise the real Playwright BrowserAgent end-to-end without ever
touching the real website. Clearly labelled as a simulation.
"""

from __future__ import annotations

from html import escape

from app.browser.raw import PageKind, RawPageObservation


def _e(value: str | None) -> str:
    return escape(value or "")


def _opt(testid: str, value: str | None, tag: str = "span") -> str:
    if value is None:
        return ""
    return f'<{tag} data-testid="{testid}">{_e(value)}</{tag}>'


_SCRIPT = """
document.querySelectorAll('[data-testid="offer-accept"]').forEach(function (btn) {
  btn.addEventListener('click', function () {
    var offer = btn.closest('[data-testid="upgrade-offer"]');
    var price = offer.querySelector('[data-testid="offer-price"]');
    var miles = offer.querySelector('[data-testid="offer-miles"]');
    var priceText = price ? price.textContent : '';
    var free = /gratuit|^\\s*0\\s*€/i.test(priceText);
    var box = document.getElementById('confirmation');
    box.hidden = false;
    box.dataset.offerId = offer.dataset.offerId;
    document.querySelector('[data-testid="confirm-total"]').textContent = 'Total : ' + (free ? '0 €' : priceText);
    document.querySelector('[data-testid="confirm-miles"]').textContent = miles ? miles.textContent : '0 Miles';
    document.getElementById('payment').hidden = free;
  });
});
document.querySelector('[data-testid="confirm-final"]').addEventListener('click', function () {
  document.querySelectorAll('[data-testid="passenger-cabin"]').forEach(function (c) { c.textContent = 'Business'; });
  var cabin = document.querySelector('[data-testid="booking-cabin"]');
  if (cabin) { cabin.textContent = 'Business'; }
  document.querySelectorAll('[data-testid="upgrade-offer"]').forEach(function (o) { o.remove(); });
  document.getElementById('confirmation').hidden = true;
  var msgs = document.getElementById('messages');
  msgs.innerHTML = '<p data-testid="page-message">Votre surclassement en Business est confirmé.</p>';
});
"""


def render_mock_page(raw: RawPageObservation) -> str:
    banner = '<p class="sim">SIMULATION - MOCK AIR FRANCE - données fictives</p>'
    messages = "".join(f'<p data-testid="page-message">{_e(m)}</p>' for m in raw.messages)
    if raw.page_kind is PageKind.LOGIN:
        body = '<form data-testid="login-form"><label>Identifiant <input></label></form>'
    elif raw.page_kind is PageKind.CAPTCHA:
        body = '<div data-testid="captcha">Vérification requise</div>'
    elif raw.page_kind is PageKind.NOT_FOUND:
        body = '<div data-testid="booking-not-found">Réservation introuvable</div>'
    else:
        passengers = "".join(
            '<li data-testid="passenger-row">'
            + _opt("passenger-name", p.name_text)
            + _opt("passenger-ticket", p.ticket_text)
            + _opt("passenger-cabin", p.cabin_text)
            + _opt("passenger-seat", p.seat_text)
            + _opt("passenger-eligibility", p.eligibility_text)
            + "</li>"
            for p in raw.passenger_rows
        )
        offers = "".join(
            f'<div data-testid="upgrade-offer" data-offer-id="{_e(o.offer_id)}">'
            + _opt("offer-cabin", o.cabin_text)
            + _opt("offer-price", o.price_text)
            + _opt("offer-miles", o.miles_text)
            + _opt("offer-passengers", o.passengers_text)
            + _opt("offer-availability", o.availability_text)
            + (
                '<button data-testid="offer-accept">Surclasser</button>'
                if o.has_accept_button
                else ""
            )
            + "</div>"
            for o in raw.upgrade_offers
        )
        body = (
            '<nav data-testid="account-menu">Mon compte</nav>'
            '<main data-testid="booking-details">'
            + _opt("booking-reference", raw.booking_reference_text, "strong")
            + _opt("flight-number", raw.flight_number_text)
            + _opt("origin", raw.origin_text)
            + _opt("destination", raw.destination_text)
            + _opt("departure", raw.departure_text)
            + _opt("aircraft", raw.aircraft_text)
            + _opt("passengers-count", raw.passengers_count_text)
            + _opt("booking-cabin", raw.cabin_text)
            + _opt("business-availability", raw.business_availability_text)
            + _opt("business-seats", raw.business_seats_text)
            + _opt("checkin-status", raw.checkin_text)
            + f"<ul>{passengers}</ul><section>{offers}</section>"
            + '<section id="confirmation" hidden>'
            '<span data-testid="confirm-total"></span><span data-testid="confirm-miles"></span>'
            '<div id="payment" data-testid="payment-form" hidden>Paiement par carte</div>'
            '<button data-testid="confirm-final">Confirmer</button></section>'
            "</main>"
        )
    script = f"<script>{_SCRIPT}</script>" if raw.page_kind is PageKind.BOOKING else ""
    return (
        '<!doctype html><html lang="fr"><head><meta charset="utf-8">'
        "<title>MOCK AIR FRANCE</title></head><body>"
        f'{banner}{body}<div id="messages">{messages}</div>{script}</body></html>'
    )
