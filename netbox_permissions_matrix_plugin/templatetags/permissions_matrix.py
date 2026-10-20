"""Template filters for the plugin's pages."""

import json

from django import template

register = template.Library()


@register.filter
def tojson(value) -> str:
    """Constraints as compact JSON, as the matrix's tooltips and the review show them, not as Python reprs."""
    return json.dumps(value, separators=(",", ":"))
