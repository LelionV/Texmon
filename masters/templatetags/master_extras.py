"""
Template filter supporting the registry-driven master_list.html: since the
list of columns to display comes from masters/registry.py at runtime (a
plain list of field-name strings), the template needs a way to look up
`obj.<dynamic column name>` that Django's dot-lookup syntax can't express
directly (`{{ obj.col }}` only works for a literal attribute named "col").
"""

from django import template

register = template.Library()


@register.filter
def getattribute(obj, attr_name):
    value = getattr(obj, attr_name, "")
    # Follow FK relations' __str__ automatically (e.g. currency -> "USD ($)")
    return value
