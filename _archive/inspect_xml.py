import zipfile
import xml.dom.minidom
import os

# --- CONFIGURATION ---
# Replace this with your exact filename
DOCX_FILE = "test_data/synthetic/test.docx"

def pretty_print_xml(xml_string):
    """Parses and pretty-prints an XML string."""
    try:
        dom = xml.dom.minidom.parseString(xml_string)
        return dom.toprettyxml(indent="  ")
    except Exception as e:
        return f"Error parsing XML for pretty printing: {e}\nRaw content: {xml_string[:500]}..."

def inspect_docx(filename):
    if not os.path.exists(filename):
        print(f"ERROR: File '{filename}' not found.")
        return

    print(f"--- INSPECTING: {filename} ---\n")

    try:
        with zipfile.ZipFile(filename, 'r') as z:
            # List of specific XML files we care about for comments
            targets = ['word/comments.xml', 'word/commentsExtended.xml']
            
            for target in targets:
                print(f"{'='*20} {target} {'='*20}")
                if target in z.namelist():
                    content = z.read(target)
                    # Pretty print the XML
                    pretty_content = pretty_print_xml(content)
                    
                    # Truncate if huge, but usually comments files are manageable.
                    # For this debug, let's print the first 4000 chars which usually captures the structure 
                    # and the first few comments/threads.
                    print(pretty_content[:4000]) 
                    
                    if len(pretty_content) > 4000:
                        print(f"\n... [Truncated. Total length: {len(pretty_content)} chars] ...")
                else:
                    print(f"[NOT FOUND] This file does not exist in the .docx archive.")
                print("\n")

    except zipfile.BadZipFile:
        print("ERROR: The file is not a valid .docx (zip) archive.")
    except Exception as e:
        print(f"ERROR: An unexpected error occurred: {e}")

if __name__ == "__main__":
    inspect_docx(DOCX_FILE)