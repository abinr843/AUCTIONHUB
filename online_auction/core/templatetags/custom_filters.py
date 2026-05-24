from django import template
from django.conf import settings
import os
register = template.Library()

@register.filter
def subtract(value, arg):
    """Subtracts `arg` from `value` and returns the result."""
    try:
        return float(value) - float(arg)
    except (ValueError, TypeError):
        return 0  # Return 0 if invalid input

@register.filter
def absolute(value):
    """Returns the absolute value of a number."""
    try:
        return abs(float(value))
    except (ValueError, TypeError):
        return 0




@register.filter
def currency(value):
    return f"${value:,.2f}"

@register.filter
def bid_class(value):
    if value > 0:
        return 'positive'
    elif value < 0:
        return 'negative'
    return 'neutral'


@register.filter
def generate_color(username):
    """Generate a color based on the username."""
    hash_value = sum(ord(char) for char in username)
    hue = hash_value % 360
    return f"hsl({hue}, 70%, 40%)"

@register.filter
def times(number):
    return range(number)
@register.filter
def split(value, delimiter):
    """Split a string by a delimiter."""
    if value:
        return value.split(delimiter)
    return []

@register.filter
def mediaprefix(value):
    """Prepend MEDIA_URL to a file path."""
    return f"{settings.MEDIA_URL}{value}"

@register.filter
def basename(value):
    """Extract the filename from a path."""
    return os.path.basename(value)