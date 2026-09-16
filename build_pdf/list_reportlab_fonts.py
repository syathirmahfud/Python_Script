from reportlab.pdfbase import pdfmetrics

print(sorted(pdfmetrics.getRegisteredFontNames()))