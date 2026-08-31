import xml.etree.ElementTree as ET
import re

# Parse the XML file
tree = ET.parse('./extracted/word/document.xml')
root = tree.getroot()

# Define namespace
ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}

# Extract all text elements
text_content = []
for elem in root.iter():
    # Check if this is a text element
    if elem.tag.endswith('}t'):
        if elem.text:
            text_content.append(elem.text)

# Join and clean up
full_text = ' '.join(text_content)

# Write to file
with open('specification_text.txt', 'w', encoding='utf-8') as f:
    f.write(full_text)

print('Specification extracted successfully')
print('First 1000 characters:')
print(full_text[:1000])
