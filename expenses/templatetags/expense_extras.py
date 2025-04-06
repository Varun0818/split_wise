from django import template

register = template.Library()

@register.filter
def get_item(dictionary, key):
    """
    Get an item from a dictionary using a key.
    Usage: {{ dictionary|get_item:key }}
    """
    if dictionary is None:
        return None
    return dictionary.get(key)

@register.filter
def abs(value):
    """
    Return the absolute value of a number.
    Usage: {{ value|abs }}
    """
    return abs(value) if value is not None else None