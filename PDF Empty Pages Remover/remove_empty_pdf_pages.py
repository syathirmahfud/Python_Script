from pypdf import PdfReader, PdfWriter

def is_page_empty(page, min_content_length=50):
    text = page.extract_text()
    
    if text and text.strip():
        return False  # has text
    
    contents = page.get_contents()
    if contents:
        try:
            content_data = contents.get_data()
            if len(content_data) > min_content_length:
                return False  # has drawing/image content
        except:
            pass
    
    return True  # empty

reader = PdfReader("input.pdf")
writer = PdfWriter()

for i, page in enumerate(reader.pages):
    if not is_page_empty(page):
        writer.add_page(page)
    else:
        print(f"Deleted empty page {i + 1}")

with open("output_no_empty_pages.pdf", "wb") as f:
    writer.write(f)

print("Finished removing empty pages.")
