from django.contrib import admin
from .models import DocumentSequence


@admin.register(DocumentSequence)
class DocumentSequenceAdmin(admin.ModelAdmin):
    list_display = ("prefix", "year", "last_number")
    list_filter = ("prefix", "year")
    ordering = ("-year", "prefix")
